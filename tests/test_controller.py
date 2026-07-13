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
- ``_process_task`` — worker orchestrator.
  * pre-cancelled → early return, no download
  * successful download → PROCESSING/DONE state transitions
  * Bandcamp/SoundCloud skip post_process (yt-dlp already tagged)
  * Other platforms run post_process when auto_fix_metadata=True
  * dj_enrich runs on any platform when dj_enrich=True
  * dedup_check called when dedupe_audio_fp=True
  * record_download bumped ONLY on success + DONE
  * cross_platform_retry called ONLY on failure with config on
- ``_post_process`` — cover art + metadata rewrite.
  * skips cover download when track.cover_url is empty
  * always calls write_metadata + verify_and_fix
  * exceptions swallowed (logged, not raised)
- ``_dj_enrich`` — Beatport BPM/key/Camelot enrichment.
  * builds the entry dict correctly from the task
  * passes config values through to dj_metadata.enrich_files
  * follows file renames (DJ-filename option)
  * exceptions swallowed
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


# ─────────────────────────────────────────────────────────────────────────
# _process_task — worker orchestrator
# ─────────────────────────────────────────────────────────────────────────

def _pending_task(*, platform="spotify", output_path=None) -> DownloadTask:
    """Build a task in PENDING state ready to be run through _process_task."""
    task = DownloadTask(
        track=_track(platform=platform, source_url="https://x"),
        profile=get_profile("mp3", "320"),
        output_dir=".",
    )
    task.status = DownloadStatus.PENDING
    if output_path is not None:
        task.output_path = output_path
    return task


def _run_process(ctrl, task, *, success=True, final_output=None):
    """Common helper: patch the downloader + collaborators, run the worker.

    The download side effect mirrors what AudioDownloader really does:
    set output_path, flip status to DONE/ERROR, and return the success
    flag (returning it explicitly is critical — a side_effect that
    returns None *overrides* the mock's return_value with None).
    """
    def _download_side_effect(t):
        if final_output is not None:
            t.output_path = final_output
        if success:
            t.status   = DownloadStatus.DONE
            t.progress = 100.0
        else:
            t.status = DownloadStatus.ERROR
        return success

    ctrl.downloader.download = MagicMock(side_effect=_download_side_effect)
    ctrl._notify = MagicMock()
    with patch.object(ctrl, "_post_process") as post, \
         patch.object(ctrl, "_dj_enrich") as enrich, \
         patch.object(ctrl, "_dedup_check", return_value=False) as dedup, \
         patch.object(ctrl, "_try_cross_platform_retry") as retry, \
         patch("utils.donor_gate.record_download") as record:
        ctrl._process_task(task)
    return {
        "download":  ctrl.downloader.download,
        "post":      post,
        "enrich":    enrich,
        "dedup":     dedup,
        "retry":     retry,
        "record":    record,
        "notify":    ctrl._notify,
    }


def test_process_task_early_return_when_cancelled(bare_ctrl):
    """Task already CANCELLED (e.g. user removed it from queue) → no work."""
    task = _pending_task()
    task.status = DownloadStatus.CANCELLED
    bare_ctrl.downloader.download = MagicMock()
    bare_ctrl._process_task(task)
    bare_ctrl.downloader.download.assert_not_called()


def test_process_task_success_calls_notify_and_records(tmp_path, bare_ctrl):
    """Successful download → notify fires + record_download called once."""
    bare_ctrl._config = {}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["download"].assert_called_once_with(task)
    m["record"].assert_called_once()
    assert task.status == DownloadStatus.DONE
    # Notify is called at least twice: DOWNLOADING transition + final state.
    assert m["notify"].call_count >= 2


def test_process_task_skips_post_process_for_bandcamp(tmp_path, bare_ctrl):
    """Bandcamp downloads are yt-dlp-native — post_process would overwrite
    good metadata with the thinner search-API version."""
    bare_ctrl._config = {"auto_fix_metadata": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="bandcamp", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["post"].assert_not_called()


def test_process_task_skips_post_process_for_soundcloud(tmp_path, bare_ctrl):
    bare_ctrl._config = {"auto_fix_metadata": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="soundcloud", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["post"].assert_not_called()


def test_process_task_runs_post_process_on_spotify(tmp_path, bare_ctrl):
    """Spotify tracks lack native tags; auto_fix_metadata does the work."""
    bare_ctrl._config = {"auto_fix_metadata": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="spotify", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["post"].assert_called_once()


def test_process_task_skips_post_process_when_disabled(tmp_path, bare_ctrl):
    bare_ctrl._config = {"auto_fix_metadata": False}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="spotify", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["post"].assert_not_called()


def test_process_task_runs_dj_enrich_on_bandcamp_when_enabled(tmp_path, bare_ctrl):
    """DJ enrichment (BPM/key) is orthogonal to platform — Bandcamp too."""
    bare_ctrl._config = {"dj_enrich": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="bandcamp", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["enrich"].assert_called_once()


def test_process_task_skips_dj_enrich_when_disabled(tmp_path, bare_ctrl):
    bare_ctrl._config = {"dj_enrich": False}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="spotify", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["enrich"].assert_not_called()


def test_process_task_dedup_check_called_when_configured(tmp_path, bare_ctrl):
    bare_ctrl._config = {"dedupe_audio_fp": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="spotify", output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["dedup"].assert_called_once()


def test_process_task_no_record_download_on_failure(tmp_path, bare_ctrl):
    """Freemium counter must NOT bump on failed downloads."""
    bare_ctrl._config = {}
    task = _pending_task()
    m = _run_process(bare_ctrl, task, success=False)
    m["record"].assert_not_called()


def test_process_task_cross_platform_retry_on_failure(tmp_path, bare_ctrl):
    """Failed + ERROR + config on → retry hook fires."""
    bare_ctrl._config = {"cross_platform_retry": True}
    task = _pending_task()
    m = _run_process(bare_ctrl, task, success=False)
    m["retry"].assert_called_once_with(task)


def test_process_task_no_retry_when_config_off(tmp_path, bare_ctrl):
    bare_ctrl._config = {"cross_platform_retry": False}
    task = _pending_task()
    m = _run_process(bare_ctrl, task, success=False)
    m["retry"].assert_not_called()


def test_process_task_no_retry_on_success(tmp_path, bare_ctrl):
    """Successful download should never trigger the retry path."""
    bare_ctrl._config = {"cross_platform_retry": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(output_path=out)
    m = _run_process(bare_ctrl, task, success=True, final_output=out)
    m["retry"].assert_not_called()


def test_process_task_transitions_to_processing_when_post_or_enrich(tmp_path, bare_ctrl):
    """If any post-download step runs, task briefly enters PROCESSING
    before landing back in DONE — the UI uses this to show progress state.

    Snapshots task.status at each _notify() call to prove the transition
    actually happens; can't use _run_process helper here because it
    replaces _notify wholesale.
    """
    bare_ctrl._config = {"dj_enrich": True}
    out = tmp_path / "out.mp3"
    out.write_bytes(b"x")
    task = _pending_task(platform="spotify", output_path=out)

    def _download_side_effect(t):
        t.output_path = out
        t.status      = DownloadStatus.DONE
        t.progress    = 100.0
        return True
    bare_ctrl.downloader.download = MagicMock(side_effect=_download_side_effect)

    seen: list = []
    bare_ctrl._notify = MagicMock(side_effect=lambda t: seen.append(t.status))

    with patch.object(bare_ctrl, "_post_process"), \
         patch.object(bare_ctrl, "_dj_enrich"), \
         patch.object(bare_ctrl, "_dedup_check", return_value=False), \
         patch.object(bare_ctrl, "_try_cross_platform_retry"), \
         patch("utils.donor_gate.record_download"):
        bare_ctrl._process_task(task)

    assert DownloadStatus.PROCESSING in seen
    assert task.status == DownloadStatus.DONE


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


# ─────────────────────────────────────────────────────────────────────────
# _post_process — cover art + metadata rewrite
# ─────────────────────────────────────────────────────────────────────────

def _post_task(*, cover_url="", output_path=None):
    """Task ready for _post_process — path + track with optional cover."""
    track = TrackInfo(
        title="Song", artists=["Artist"], platform="spotify",
        cover_url=cover_url,
    )
    task = DownloadTask(track=track, profile=get_profile("mp3", "320"),
                        output_dir=".")
    task.output_path = output_path
    return task


def test_post_process_downloads_cover_when_url_present(tmp_path, bare_ctrl):
    out = tmp_path / "song.mp3"
    out.write_bytes(b"x")
    task = _post_task(cover_url="https://cover.example/x.jpg", output_path=out)
    with patch("core.controller.download_cover",
               return_value=b"fake-jpeg-bytes") as cover, \
         patch("core.controller.write_metadata") as wm, \
         patch("core.controller.verify_and_fix", return_value=[]):
        bare_ctrl._post_process(task)
    cover.assert_called_once_with("https://cover.example/x.jpg")
    # write_metadata got the fetched cover bytes.
    wm.assert_called_once()
    assert wm.call_args[0][2] == b"fake-jpeg-bytes"


def test_post_process_skips_cover_when_no_url(tmp_path, bare_ctrl):
    """Empty cover_url → don't hit the network at all."""
    out = tmp_path / "song.mp3"
    out.write_bytes(b"x")
    task = _post_task(cover_url="", output_path=out)
    with patch("core.controller.download_cover") as cover, \
         patch("core.controller.write_metadata") as wm, \
         patch("core.controller.verify_and_fix", return_value=[]):
        bare_ctrl._post_process(task)
    cover.assert_not_called()
    # write_metadata still called, but with cover=None.
    wm.assert_called_once()
    assert wm.call_args[0][2] is None


def test_post_process_runs_verify_and_fix(tmp_path, bare_ctrl):
    """verify_and_fix runs after metadata write; corrections logged."""
    out = tmp_path / "song.mp3"
    out.write_bytes(b"x")
    task = _post_task(output_path=out)
    with patch("core.controller.download_cover"), \
         patch("core.controller.write_metadata"), \
         patch("core.controller.verify_and_fix",
               return_value=["artist", "title"]) as vf:
        bare_ctrl._post_process(task)
    vf.assert_called_once()


def test_post_process_swallows_write_metadata_error(tmp_path, bare_ctrl):
    """Any exception in the chain must be logged, not propagated —
    a botched tag write shouldn't abort the whole task."""
    out = tmp_path / "song.mp3"
    out.write_bytes(b"x")
    task = _post_task(output_path=out)
    with patch("core.controller.download_cover"), \
         patch("core.controller.write_metadata",
               side_effect=OSError("mutagen exploded")), \
         patch("core.controller.verify_and_fix"):
        bare_ctrl._post_process(task)   # must not raise


def test_post_process_swallows_cover_download_error(tmp_path, bare_ctrl):
    out = tmp_path / "song.mp3"
    out.write_bytes(b"x")
    task = _post_task(cover_url="https://cover.example/x.jpg", output_path=out)
    with patch("core.controller.download_cover",
               side_effect=Exception("network down")), \
         patch("core.controller.write_metadata"), \
         patch("core.controller.verify_and_fix"):
        bare_ctrl._post_process(task)


# ─────────────────────────────────────────────────────────────────────────
# _dj_enrich — Beatport BPM/key/Camelot pipeline
# ─────────────────────────────────────────────────────────────────────────

def _enrich_task(*, output_path=None, genre="House", cover_url="",
                 year="", track_number=0, total_tracks=0):
    track = TrackInfo(
        title="Track", artists=["Artist"], platform="spotify",
        genre=genre, cover_url=cover_url, year=year,
        track_number=track_number, total_tracks=total_tracks,
    )
    task = DownloadTask(track=track, profile=get_profile("mp3", "320"),
                        output_dir=".")
    task.output_path = output_path
    return task


def test_dj_enrich_calls_enrich_files_with_correct_entry(tmp_path, bare_ctrl):
    """The entry dict passed to enrich_files must contain all the fields
    dj_metadata expects — path, artist, title, genre, cover_url, year,
    track_number, tracks_count."""
    out = tmp_path / "track.mp3"
    task = _enrich_task(
        output_path=out, genre="Techno", cover_url="https://cover",
        year="2024", track_number=2, total_tracks=10,
    )
    with patch("metadata.dj_metadata.enrich_files",
               return_value={"tagged": 1, "renames": {}}) as enrich:
        bare_ctrl._dj_enrich(task)

    enrich.assert_called_once()
    entries, fmt = enrich.call_args[0][0], enrich.call_args[0][1]
    assert len(entries) == 1
    e = entries[0]
    assert e["path"]         == str(out)
    assert e["artist"]       == "Artist"
    assert e["title"]        == "Track"
    assert e["genre"]        == "Techno"
    assert e["cover_url"]    == "https://cover"
    assert e["year"]         == "2024"
    assert e["track_number"] == 2
    assert e["tracks_count"] == 10
    assert fmt == "mp3"


def test_dj_enrich_forwards_config_flags(tmp_path, bare_ctrl):
    """Config toggles must reach dj_metadata: api_key, local fallback,
    replaygain, quality check, dj_filename — otherwise features silently
    do nothing."""
    bare_ctrl._config = {
        "dj_getsongbpm_key":  "APIKEY123",
        "dj_local_fallback":  True,
        "preferred_quality":  "flac",
        "dj_quality_check":   True,
        "dj_filename":        True,
        "dj_replaygain":      True,
    }
    out = tmp_path / "track.mp3"
    task = _enrich_task(output_path=out)
    with patch("metadata.dj_metadata.enrich_files",
               return_value={"tagged": 1, "renames": {}}) as enrich:
        bare_ctrl._dj_enrich(task)

    kwargs = enrich.call_args[1]
    assert kwargs["api_key"]            == "APIKEY123"
    assert kwargs["use_local_fallback"] is True
    assert kwargs["requested_quality"]  == "flac"
    assert kwargs["check_quality"]      is True
    assert kwargs["dj_filename"]        is True
    assert kwargs["replaygain"]         is True
    # cover already embedded by _post_process — this call should skip it.
    assert kwargs["embed_covers"]       is False


def test_dj_enrich_follows_rename_of_output_path(tmp_path, bare_ctrl):
    """When the dj_filename option renames the file to
    'Track [BPM - Camelot].mp3', task.output_path must follow."""
    orig = tmp_path / "old_name.mp3"
    new  = tmp_path / "Track [128 - 8A].mp3"
    task = _enrich_task(output_path=orig)
    with patch("metadata.dj_metadata.enrich_files",
               return_value={"tagged": 1, "renames": {str(orig): str(new)}}):
        bare_ctrl._dj_enrich(task)
    assert task.output_path == new


def test_dj_enrich_leaves_path_when_no_rename(tmp_path, bare_ctrl):
    orig = tmp_path / "track.mp3"
    task = _enrich_task(output_path=orig)
    with patch("metadata.dj_metadata.enrich_files",
               return_value={"tagged": 1, "renames": {}}):
        bare_ctrl._dj_enrich(task)
    assert task.output_path == orig


def test_dj_enrich_swallows_enrich_files_error(tmp_path, bare_ctrl):
    """Failures in Beatport scraping / GetSongBPM / librosa must be
    logged, never propagated — DJ metadata is optional value-add."""
    task = _enrich_task(output_path=tmp_path / "x.mp3")
    with patch("metadata.dj_metadata.enrich_files",
               side_effect=RuntimeError("beatport 500")):
        bare_ctrl._dj_enrich(task)   # must not raise


def test_dj_enrich_uses_downloader_ffmpeg_path(tmp_path, bare_ctrl):
    """When the downloader has _ffmpeg_path set (bundled ffmpeg location),
    _dj_enrich must pass THAT path — not fall back to system 'ffmpeg' —
    so DJ enrichment works in the frozen .exe too."""
    bare_ctrl.downloader._ffmpeg_path = "/opt/custom/ffmpeg"
    task = _enrich_task(output_path=tmp_path / "x.mp3")
    with patch("metadata.dj_metadata.enrich_files",
               return_value={"tagged": 1, "renames": {}}) as enrich:
        bare_ctrl._dj_enrich(task)
    assert enrich.call_args[1]["ffmpeg"] == "/opt/custom/ffmpeg"


# ─────────────────────────────────────────────────────────────────────────
# add_to_queue — freemium gate + folder structure + executor submit
# ─────────────────────────────────────────────────────────────────────────

from concurrent.futures import ThreadPoolExecutor  # noqa: E402
from core.controller import DonorGateBlocked  # noqa: E402


@pytest.fixture
def queue_ctrl(tmp_path):
    """AppController just wired-up enough for queue-management tests.

    We DO instantiate the ThreadPoolExecutor here so submit() doesn't
    explode, but the process function is patched at each test so no
    real download work happens.
    """
    c = AppController.__new__(AppController)
    c._config     = {"download_folder": str(tmp_path / "downloads")}
    c._queue      = []
    c._queue_lock = threading.Lock()
    c._dedup_lock = threading.Lock()
    c.search_manager = MagicMock()
    c.downloader    = MagicMock()
    c._on_task_update = None
    # Real executor so submit() runs (we'll patch _process_task).
    c._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="test-dl")
    yield c
    c._executor.shutdown(wait=True)


def _sample_track(**kw):
    """A minimal TrackInfo good enough for add_to_queue."""
    kw.setdefault("title", "Song")
    kw.setdefault("artists", ["Artist"])
    kw.setdefault("platform", "spotify")
    kw.setdefault("source_url", "https://x/y")
    return TrackInfo(**kw)


def test_add_to_queue_raises_when_freemium_limit_hit(queue_ctrl):
    """When can_download() returns False, add_to_queue must raise
    DonorGateBlocked so the UI can show the lockout dialog."""
    with patch("utils.donor_gate.can_download", return_value=False), \
         patch.object(queue_ctrl, "_process_task"):
        with pytest.raises(DonorGateBlocked):
            queue_ctrl.add_to_queue(_sample_track())
    # Queue must NOT contain the task on a blocked call.
    assert queue_ctrl._queue == []


def test_add_to_queue_appends_task_and_submits(queue_ctrl):
    """Normal path: task ends up in _queue AND gets submitted to executor."""
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task") as pt, \
         patch.object(queue_ctrl, "_notify"):
        task = queue_ctrl.add_to_queue(_sample_track())
    assert task in queue_ctrl._queue
    # _process_task runs on the executor — wait for it.
    queue_ctrl._executor.shutdown(wait=True)
    pt.assert_called_once_with(task)


def test_add_to_queue_notifies_immediately(queue_ctrl):
    """UI should get an immediate PENDING notification before the download
    thread even starts."""
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify") as notify:
        queue_ctrl.add_to_queue(_sample_track())
    notify.assert_called_once()


def test_add_to_queue_uses_config_format_and_quality(queue_ctrl, tmp_path):
    queue_ctrl._config.update({
        "preferred_format":  "flac",
        "preferred_quality": "best",
    })
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        task = queue_ctrl.add_to_queue(_sample_track())
    assert task.profile.format.value  == "flac"


def test_add_to_queue_uses_config_folder_structure(queue_ctrl):
    queue_ctrl._config["folder_structure"] = "{artist}/{title}"
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        task = queue_ctrl.add_to_queue(_sample_track())
    assert task.structure == "{artist}/{title}"


def test_add_to_queue_prepends_platform_subfolder_when_enabled(queue_ctrl):
    """subfolder_per_platform=True → 'Spotify/{artist}/{album}/...'"""
    queue_ctrl._config["subfolder_per_platform"] = True
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        task = queue_ctrl.add_to_queue(_sample_track(platform="spotify"))
    assert task.structure.startswith("Spotify/")


def test_add_to_queue_platform_subfolder_falls_back_to_other(queue_ctrl):
    """An unknown platform (YouTube isn't in the _PLATFORM_SUBDIR map)
    lands under 'Other/'."""
    queue_ctrl._config["subfolder_per_platform"] = True
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        task = queue_ctrl.add_to_queue(_sample_track(platform="youtube"))
    assert task.structure.startswith("Other/")


def test_add_to_queue_creates_output_dir(queue_ctrl, tmp_path):
    """ensure_dir must be called so the download can write into it —
    first-time users have no 'downloads/' folder yet."""
    target = tmp_path / "brand_new" / "downloads"
    queue_ctrl._config["download_folder"] = str(target)
    assert not target.exists()
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        queue_ctrl.add_to_queue(_sample_track())
    assert target.exists()


# ─────────────────────────────────────────────────────────────────────────
# add_album_to_queue
# ─────────────────────────────────────────────────────────────────────────

def _album(title="Album", source_url="https://album/url"):
    return TrackInfo(title=title, artists=["Artist"],
                     platform="spotify", source_url=source_url,
                     is_album=True)


def test_add_album_expands_to_tracks_and_enqueues(queue_ctrl):
    album = _album()
    queue_ctrl.search_manager.resolve_url.return_value = [
        _sample_track(title="S1"),
        _sample_track(title="S2"),
        _sample_track(title="S3"),
    ]
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        n = queue_ctrl.add_album_to_queue(album)
    assert n == 3
    assert len(queue_ctrl._queue) == 3


def test_add_album_filters_placeholder_album_entries(queue_ctrl):
    """resolve_url can return the album itself alongside its tracks; the
    album placeholder must be dropped so it isn't re-queued recursively."""
    album = _album()
    queue_ctrl.search_manager.resolve_url.return_value = [
        _album(title="ThisAlbum"),           # is_album=True → dropped
        _sample_track(title="S1"),
        _sample_track(title="S2"),
    ]
    with patch("utils.donor_gate.can_download", return_value=True), \
         patch.object(queue_ctrl, "_process_task"), \
         patch.object(queue_ctrl, "_notify"):
        n = queue_ctrl.add_album_to_queue(album)
    assert n == 2


def test_add_album_returns_zero_when_resolve_returns_empty(queue_ctrl):
    """Provider returned []  (private/deleted album) → don't try to
    enqueue anything, return 0."""
    album = _album()
    queue_ctrl.search_manager.resolve_url.return_value = []
    n = queue_ctrl.add_album_to_queue(album)
    assert n == 0


def test_add_album_returns_zero_when_resolve_raises(queue_ctrl):
    """Provider exception must be logged, not propagated."""
    album = _album()
    queue_ctrl.search_manager.resolve_url.side_effect = RuntimeError("boom")
    n = queue_ctrl.add_album_to_queue(album)
    assert n == 0


def test_add_album_returns_zero_when_no_source_url(queue_ctrl):
    """No URL means we can't resolve — skip cleanly."""
    album = _album(source_url="")
    n = queue_ctrl.add_album_to_queue(album)
    assert n == 0


# ─────────────────────────────────────────────────────────────────────────
# enqueue_result — album/track dispatch
# ─────────────────────────────────────────────────────────────────────────

def test_enqueue_result_dispatches_to_album_for_album(queue_ctrl):
    album = _album()
    with patch.object(queue_ctrl, "add_album_to_queue",
                      return_value=5) as ab, \
         patch.object(queue_ctrl, "add_to_queue") as at:
        n = queue_ctrl.enqueue_result(album)
    ab.assert_called_once_with(album)
    at.assert_not_called()
    assert n == 5


def test_enqueue_result_dispatches_to_track_for_single(queue_ctrl):
    track = _sample_track()
    with patch.object(queue_ctrl, "add_album_to_queue") as ab, \
         patch.object(queue_ctrl, "add_to_queue") as at:
        n = queue_ctrl.enqueue_result(track)
    at.assert_called_once_with(track)
    ab.assert_not_called()
    assert n == 1


# ─────────────────────────────────────────────────────────────────────────
# remove_from_queue
# ─────────────────────────────────────────────────────────────────────────

def test_remove_from_queue_signals_downloader_cancel(queue_ctrl):
    task = _pending_task()
    queue_ctrl._queue.append(task)
    with patch.object(queue_ctrl, "_notify"):
        queue_ctrl.remove_from_queue(task)
    queue_ctrl.downloader.cancel.assert_called_once_with(task.task_id)


def test_remove_from_queue_flips_status_to_cancelled(queue_ctrl):
    task = _pending_task()
    task.status = DownloadStatus.PENDING
    queue_ctrl._queue.append(task)
    with patch.object(queue_ctrl, "_notify"):
        queue_ctrl.remove_from_queue(task)
    assert task.status == DownloadStatus.CANCELLED


def test_remove_from_queue_does_not_change_terminal_status(queue_ctrl):
    """A DONE or ERROR task keeps its status — the row was final already."""
    task = _pending_task()
    task.status = DownloadStatus.DONE
    queue_ctrl._queue.append(task)
    with patch.object(queue_ctrl, "_notify"):
        queue_ctrl.remove_from_queue(task)
    assert task.status == DownloadStatus.DONE


def test_remove_from_queue_removes_from_internal_list(queue_ctrl):
    task = _pending_task()
    queue_ctrl._queue.append(task)
    with patch.object(queue_ctrl, "_notify"):
        queue_ctrl.remove_from_queue(task)
    assert task not in queue_ctrl._queue


def test_remove_from_queue_tolerates_missing_task(queue_ctrl):
    """The task might already be gone from _queue (e.g. clear_completed
    ran first).  The remove call must not raise."""
    task = _pending_task()
    task.status = DownloadStatus.PENDING
    with patch.object(queue_ctrl, "_notify"):
        queue_ctrl.remove_from_queue(task)   # not in queue — must not raise


# ─────────────────────────────────────────────────────────────────────────
# clear_completed
# ─────────────────────────────────────────────────────────────────────────

def test_clear_completed_removes_terminal_tasks(queue_ctrl):
    t_pending    = _pending_task(); t_pending.status    = DownloadStatus.PENDING
    t_downloading= _pending_task(); t_downloading.status= DownloadStatus.DOWNLOADING
    t_done       = _pending_task(); t_done.status       = DownloadStatus.DONE
    t_error      = _pending_task(); t_error.status      = DownloadStatus.ERROR
    t_cancelled  = _pending_task(); t_cancelled.status  = DownloadStatus.CANCELLED
    queue_ctrl._queue = [t_pending, t_downloading, t_done, t_error, t_cancelled]

    queue_ctrl.clear_completed()

    assert queue_ctrl._queue == [t_pending, t_downloading]


def test_clear_completed_empty_queue_is_safe(queue_ctrl):
    queue_ctrl._queue = []
    queue_ctrl.clear_completed()   # must not raise
    assert queue_ctrl._queue == []
