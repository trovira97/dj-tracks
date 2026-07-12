"""Tests for the AppController hotspots — the retry/dedup/enrich
control flow that a fresh AppController.__init__() would drag in a
lot of state to test.

The tests here build minimal controllers via ``AppController.__new__``
+ hand-set fields, so they exercise the actual method bodies against
mocked collaborators instead of pulling in a real SearchManager +
AudioDownloader + thread pool.

Focus:
- ``_try_cross_platform_retry`` — the flow triggered by the O.B.I.
  bug we shipped a fix for.  Regression guards for:
  * only fires on irrecoverable errors (not 403/network)
  * one-shot per task (no infinite loops)
  * empty query short-circuit
  * search failure short-circuit
  * candidates filtered by platform + album status
  * platform preference order (Bandcamp > SoundCloud > Spotify > Apple)
  * candidates with source_url ranked ahead of those without
- ``_dedup_check`` — Chromaprint-based acoustic dup guard.
  * disabled-by-config path
  * Chromaprint not available path
  * duplicate detected → file deleted + task flagged as error
  * new track → fingerprint written to index
"""
from __future__ import annotations

import threading
from unittest.mock import MagicMock, patch

import pytest

from core.controller import AppController
from downloader.audio_downloader import DownloadStatus, DownloadTask
from downloader.quality_manager import get_profile
from providers import TrackInfo


# ─────────────────────────────────────────────────────────────────────────
# Fixtures — build a bare AppController without touching config/providers
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def bare_ctrl():
    """A minimally-initialised AppController that skips __init__.

    Instead of instantiating providers + thread pool we hand-set
    just the fields the method under test touches.
    """
    c = AppController.__new__(AppController)
    c._config     = {}
    c._queue      = []
    c._queue_lock = threading.Lock()
    c._dedup_lock = threading.Lock()
    c.search_manager = MagicMock()
    c.downloader    = MagicMock()
    return c


def _track(*, platform="soundcloud", title="Dont Give Up",
           artists=("O.B.I.",), source_url="https://soundcloud.com/x/y",
           is_album=False):
    return TrackInfo(
        title=title, artists=list(artists),
        platform=platform, source_url=source_url, is_album=is_album,
    )


def _failed_task(*, error_raw="", error_msg="", track_kw=None) -> DownloadTask:
    track = _track(**(track_kw or {}))
    task = DownloadTask(track=track, profile=get_profile("mp3", "320"),
                        output_dir=".")
    task.status    = DownloadStatus.ERROR
    task.error_msg = error_msg
    task.error_raw = error_raw
    return task


# ─────────────────────────────────────────────────────────────────────────
# _try_cross_platform_retry
# ─────────────────────────────────────────────────────────────────────────

def test_retry_noop_on_recoverable_error(bare_ctrl):
    """403 / network → NOT irrecoverable → don't retry cross-platform."""
    task = _failed_task(error_raw="HTTP Error 403: Forbidden")
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    add.assert_not_called()


def test_retry_noop_when_already_retried(bare_ctrl):
    """A single retry per task — no infinite loops if alt also fails."""
    task = _failed_task(error_raw="HTTP Error 404: Not Found")
    task._retried_cross_platform = True   # simulate a prior retry
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    add.assert_not_called()


def test_retry_noop_on_empty_query(bare_ctrl):
    task = _failed_task(
        error_raw="HTTP Error 404: Not Found",
        track_kw={"title": "", "artists": ()},
    )
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    add.assert_not_called()


def test_retry_noop_when_search_raises(bare_ctrl):
    """Search backend crash must not propagate — we just log and skip."""
    task = _failed_task(error_raw="HTTP Error 404: Not Found")
    bare_ctrl.search_manager.search.side_effect = RuntimeError("boom")
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    add.assert_not_called()


def test_retry_noop_when_no_alternatives(bare_ctrl):
    """Search returned only the failed platform → no candidate to try."""
    task = _failed_task(error_raw="HTTP Error 404: Not Found",
                         track_kw={"platform": "soundcloud"})
    bare_ctrl.search_manager.search.return_value = [
        _track(platform="soundcloud", source_url="https://soundcloud.com/a/b"),
    ]
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    add.assert_not_called()


def test_retry_filters_out_original_platform(bare_ctrl):
    """The platform that just failed is never a candidate."""
    task = _failed_task(error_raw="404 Not Found",
                         track_kw={"platform": "soundcloud"})
    bare_ctrl.search_manager.search.return_value = [
        _track(platform="soundcloud", source_url="sc"),   # excluded
        _track(platform="youtube",    source_url="yt"),
    ]
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    add.assert_called_once()
    picked = add.call_args[0][0]
    assert picked.platform == "youtube"


def test_retry_filters_out_albums(bare_ctrl):
    task = _failed_task(error_raw="404",
                         track_kw={"platform": "soundcloud"})
    bare_ctrl.search_manager.search.return_value = [
        _track(platform="spotify", is_album=True, source_url="sp1"),  # album — out
        _track(platform="spotify", is_album=False, source_url="sp2"),
    ]
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    picked = add.call_args[0][0]
    assert picked.is_album is False


def test_retry_prefers_bandcamp_over_soundcloud_over_spotify_over_apple(bare_ctrl):
    """Platform preference is Bandcamp > SoundCloud > Spotify > Apple Music."""
    task = _failed_task(error_raw="404",
                         track_kw={"platform": "youtube"})
    # Provide all four, in reverse-preference order to make ordering the check.
    bare_ctrl.search_manager.search.return_value = [
        _track(platform="applemusic", source_url="am"),
        _track(platform="spotify",    source_url="sp"),
        _track(platform="soundcloud", source_url="sc"),
        _track(platform="bandcamp",   source_url="bc"),
    ]
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    picked = add.call_args[0][0]
    assert picked.platform == "bandcamp"


def test_retry_prefers_candidates_with_source_url(bare_ctrl):
    """A candidate with a real source_url wins even if its platform is
    otherwise lower priority — a downloadable URL is worth more."""
    task = _failed_task(error_raw="404",
                         track_kw={"platform": "youtube"})
    bare_ctrl.search_manager.search.return_value = [
        _track(platform="bandcamp",   source_url=""),   # no URL
        _track(platform="applemusic", source_url="am"),
    ]
    with patch.object(bare_ctrl, "add_to_queue") as add:
        bare_ctrl._try_cross_platform_retry(task)
    picked = add.call_args[0][0]
    assert picked.platform == "applemusic"


def test_retry_marks_task_as_retried_to_prevent_loops(bare_ctrl):
    """After firing once, _retried_cross_platform=True — even if no
    candidate was enqueued, we don't want to try again."""
    task = _failed_task(error_raw="404",
                         track_kw={"platform": "youtube"})
    bare_ctrl.search_manager.search.return_value = []
    with patch.object(bare_ctrl, "add_to_queue"):
        bare_ctrl._try_cross_platform_retry(task)
    assert task._retried_cross_platform is True


# ─────────────────────────────────────────────────────────────────────────
# _dedup_check
# ─────────────────────────────────────────────────────────────────────────

def test_dedup_noop_when_disabled_in_config(bare_ctrl, tmp_path):
    """Feature is opt-in via config; disabled → immediate False."""
    bare_ctrl._config = {}   # 'dedupe_audio_fp' not set → default False
    task = _failed_task()
    task.output_path = tmp_path / "out.mp3"
    task.output_dir  = str(tmp_path)
    task.output_path.write_bytes(b"x")
    assert bare_ctrl._dedup_check(task) is False
    assert task.output_path.exists()   # file untouched


def test_dedup_noop_when_no_output_path(bare_ctrl):
    """A task that never produced a file can't be a dup."""
    bare_ctrl._config = {"dedupe_audio_fp": True}
    task = _failed_task()
    task.output_path = None
    assert bare_ctrl._dedup_check(task) is False


def test_dedup_noop_when_chromaprint_unavailable(bare_ctrl, tmp_path):
    """If this ffmpeg build has no Chromaprint, skip cleanly (log + False)."""
    bare_ctrl._config = {"dedupe_audio_fp": True}
    task = _failed_task()
    task.output_path = tmp_path / "out.mp3"
    task.output_dir  = str(tmp_path)
    task.output_path.write_bytes(b"x")
    with patch("metadata.dj_metadata.chromaprint_available", return_value=False):
        assert bare_ctrl._dedup_check(task) is False


def test_dedup_removes_file_on_match(bare_ctrl, tmp_path):
    """A fingerprint match against the index → delete the new file
    and mark the task as an error with the '♻ Duplicado' message."""
    bare_ctrl._config = {"dedupe_audio_fp": True}
    task = _failed_task()
    task.output_path = tmp_path / "new.mp3"
    task.output_dir  = str(tmp_path)
    task.output_path.write_bytes(b"new")
    # Pre-populate the index with an "existing" fingerprint.
    (tmp_path / ".dj_tracks_fp.json").write_text(
        '{"existing.mp3": "AAAAAAAAAA"}', encoding="utf-8")

    with patch("metadata.dj_metadata.chromaprint_available", return_value=True), \
         patch("metadata.dj_metadata.chromaprint_fingerprint",
               return_value="AAAAAAAAAA"), \
         patch("metadata.dj_metadata.fp_similarity", return_value=0.99):
        assert bare_ctrl._dedup_check(task) is True

    # File must be gone.
    assert not task.output_path.exists()
    # Task flagged as duplicate.
    assert task.status == DownloadStatus.ERROR
    assert "Duplicado" in task.error_msg


def test_dedup_writes_fingerprint_when_new_track(bare_ctrl, tmp_path):
    """First time we see this fingerprint → append to index, no delete."""
    bare_ctrl._config = {"dedupe_audio_fp": True}
    task = _failed_task()
    task.output_path = tmp_path / "brand_new.mp3"
    task.output_dir  = str(tmp_path)
    task.output_path.write_bytes(b"payload")

    with patch("metadata.dj_metadata.chromaprint_available", return_value=True), \
         patch("metadata.dj_metadata.chromaprint_fingerprint",
               return_value="ZZZZZZZZZZ"), \
         patch("metadata.dj_metadata.fp_similarity", return_value=0.0):
        assert bare_ctrl._dedup_check(task) is False

    # Index was created with our fingerprint.
    import json
    idx = json.loads((tmp_path / ".dj_tracks_fp.json").read_text(encoding="utf-8"))
    assert idx["brand_new.mp3"] == "ZZZZZZZZZZ"
    # File still there.
    assert task.output_path.exists()
