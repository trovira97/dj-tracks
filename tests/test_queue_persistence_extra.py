"""Extended tests for ``core.queue_persistence``.

There's an existing tests/test_queue_persistence.py (6 tests) that
covers basic roundtripping.  This file adds regression guards for
edge cases: terminal-status filtering, per-task defaults on missing
fields, partial-corruption tolerance, and status demotion.

The queue file is the single source of truth for "what am I in the
middle of downloading" across app restarts — a bug here silently
loses queued work.
"""
from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from core import queue_persistence
from core.queue_persistence import (
    _dict_to_task,
    _task_to_dict,
    clear_queue,
    load_queue,
    save_queue,
)
from downloader.audio_downloader import DownloadStatus, DownloadTask
from downloader.quality_manager import get_profile
from providers import TrackInfo


# ─────────────────────────────────────────────────────────────────────────
# Fixture: redirect QUEUE_PATH to a temp file per test
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _tmp_queue_path(tmp_path, monkeypatch):
    """Every test writes to its own throw-away queue.json."""
    p = tmp_path / "queue.json"
    monkeypatch.setattr(queue_persistence, "QUEUE_PATH", p)
    yield p


def _task(**kw):
    """Build a DownloadTask with sensible defaults."""
    kw.setdefault("track", TrackInfo(
        title="Get Lucky", artists=["Daft Punk"],
        album="Random Access Memories", year="2013",
        genre="Electronic", duration_ms=369_000,
        isrc="USQX91300224",
        cover_url="https://cover.jpg",
        source_url="https://open.spotify.com/track/abc",
        platform="spotify", track_id="abc",
    ))
    kw.setdefault("profile", get_profile("mp3", "320"))
    kw.setdefault("output_dir", "/downloads")
    return DownloadTask(**kw)


# ─────────────────────────────────────────────────────────────────────────
# _task_to_dict — serialization
# ─────────────────────────────────────────────────────────────────────────

def test_task_to_dict_captures_all_track_fields():
    """Every TrackInfo field the deserializer needs is in the dict."""
    task = _task()
    d = _task_to_dict(task)
    tr = d["track"]
    assert tr["title"]       == "Get Lucky"
    assert tr["artists"]     == ["Daft Punk"]
    assert tr["album"]       == "Random Access Memories"
    assert tr["year"]        == "2013"
    assert tr["genre"]       == "Electronic"
    assert tr["duration_ms"] == 369_000
    assert tr["isrc"]        == "USQX91300224"
    assert tr["cover_url"]   == "https://cover.jpg"
    assert tr["source_url"]  == "https://open.spotify.com/track/abc"
    assert tr["platform"]    == "spotify"
    assert tr["track_id"]    == "abc"


def test_task_to_dict_captures_profile_and_paths():
    """The download settings are serialised as strings that get_profile
    can reconstruct."""
    task = _task(output_dir="/custom/dir",
                 structure="{artist}/{title}")
    d = _task_to_dict(task)
    assert d["profile_format"]  == "mp3"
    assert d["profile_quality"] == "320k"
    assert d["output_dir"]      == "/custom/dir"
    assert d["structure"]       == "{artist}/{title}"


# ─────────────────────────────────────────────────────────────────────────
# _dict_to_task — deserialization + defaults
# ─────────────────────────────────────────────────────────────────────────

def test_dict_to_task_roundtrips_all_fields():
    task = _task()
    restored = _dict_to_task(_task_to_dict(task))
    assert restored is not None
    assert restored.track.title       == task.track.title
    assert restored.track.artists     == task.track.artists
    assert restored.track.isrc        == task.track.isrc
    assert restored.track.platform    == task.track.platform
    assert restored.output_dir        == task.output_dir


def test_dict_to_task_always_starts_pending():
    """Regression guard: even if the original task was DOWNLOADING or
    PROCESSING when the app was killed, the restored one must be PENDING
    so the worker pool re-picks it up cleanly."""
    task = _task()
    task.status = DownloadStatus.DOWNLOADING
    restored = _dict_to_task(_task_to_dict(task))
    assert restored.status == DownloadStatus.PENDING


def test_dict_to_task_applies_defaults_on_missing_fields():
    """A minimal dict (e.g. saved by an older app version) still loads."""
    task = _dict_to_task({})
    assert task is not None
    assert task.track.title   == "Unknown"
    assert task.track.artists == ["Unknown"]
    assert task.output_dir    == "downloads"


def test_dict_to_task_returns_none_on_malformed_track():
    """A dict where 'track' is a non-dict (schema corruption / hand-edit
    gone wrong) raises inside tr.get(...) — the try/except catches it
    and returns None so the loader can skip the bad entry."""
    bad = {"track": "not-a-dict"}
    assert _dict_to_task(bad) is None


def test_dict_to_task_unknown_quality_still_returns_task():
    """get_profile is intentionally lenient — unknown quality strings
    fall back to a sensible default rather than raising.  This means
    an old queue.json from a future/experimental release still loads."""
    d = {"profile_format": "flac", "profile_quality": "unknown-quality",
         "track": {"title": "X", "artists": ["A"]}}
    task = _dict_to_task(d)
    assert task is not None
    # Fell back to something valid instead of dying.
    assert task.profile is not None


# ─────────────────────────────────────────────────────────────────────────
# save_queue — filters terminal states
# ─────────────────────────────────────────────────────────────────────────

def test_save_queue_writes_only_non_terminal_tasks():
    """DONE / ERROR / CANCELLED tasks must NOT be persisted — they've
    finished and reloading them would show stale rows in the UI."""
    tasks = [
        _task(), _task(), _task(),
    ]
    tasks[0].status = DownloadStatus.PENDING       # → saved
    tasks[1].status = DownloadStatus.DONE          # → skipped
    tasks[2].status = DownloadStatus.DOWNLOADING   # → saved

    n = save_queue(tasks)
    assert n == 2


def test_save_queue_filters_all_terminal_states():
    tasks = []
    for state in (DownloadStatus.DONE,
                  DownloadStatus.ERROR,
                  DownloadStatus.CANCELLED):
        t = _task()
        t.status = state
        tasks.append(t)
    assert save_queue(tasks) == 0


def test_save_queue_empty_list_writes_empty_file(_tmp_queue_path):
    """Empty list still creates the file (an empty payload) so load_queue
    doesn't skip it via 'file doesn't exist'."""
    assert save_queue([]) == 0
    assert _tmp_queue_path.exists()
    payload = json.loads(_tmp_queue_path.read_text(encoding="utf-8"))
    assert payload == {"tasks": []}


def test_save_queue_returns_zero_on_write_error():
    """A disk-full / permission error while writing must degrade to
    return 0, never raise — the app is shutting down and can't recover."""
    with patch("utils.atomic_io.atomic_write_json",
               side_effect=OSError("no space left")):
        assert save_queue([_task()]) == 0


# ─────────────────────────────────────────────────────────────────────────
# load_queue — reads + handles corruption gracefully
# ─────────────────────────────────────────────────────────────────────────

def test_load_queue_returns_empty_when_file_missing(_tmp_queue_path):
    assert not _tmp_queue_path.exists()
    assert load_queue() == []


def test_load_queue_returns_empty_on_malformed_json(_tmp_queue_path):
    """A truncated or corrupted queue file must NOT crash the app on
    startup — degrade to empty and let the user re-enqueue."""
    _tmp_queue_path.write_text("{ this is not json }", encoding="utf-8")
    assert load_queue() == []


def test_load_queue_returns_empty_when_top_level_key_missing(_tmp_queue_path):
    """A JSON file without the 'tasks' key (schema change) → empty."""
    _tmp_queue_path.write_text('{"other": []}', encoding="utf-8")
    assert load_queue() == []


def test_load_queue_partial_corruption_skips_bad_entries(_tmp_queue_path):
    """One structurally-broken entry in the list (track=non-dict) must
    not lose the others."""
    good = _task_to_dict(_task())
    bad  = {"track": "not-a-dict"}   # tr.get() will raise → None returned
    _tmp_queue_path.write_text(
        json.dumps({"tasks": [good, bad, good]}), encoding="utf-8")
    tasks = load_queue()
    assert len(tasks) == 2


def test_save_then_load_roundtrips_task_data(_tmp_queue_path):
    """Full roundtrip: save a batch, load it back, fields survive."""
    original = [
        _task(track=TrackInfo(title="A", artists=["Artist1"],
                              platform="spotify")),
        _task(track=TrackInfo(title="B", artists=["Artist2"],
                              platform="youtube")),
    ]
    save_queue(original)
    restored = load_queue()
    assert len(restored) == 2
    assert {t.track.title for t in restored} == {"A", "B"}
    assert all(t.status == DownloadStatus.PENDING for t in restored)


def test_load_queue_returns_empty_on_generic_error(_tmp_queue_path):
    """A read exception (permission denied, disk error) → empty."""
    _tmp_queue_path.write_text("{}", encoding="utf-8")
    with patch("builtins.open", side_effect=PermissionError("denied")):
        assert load_queue() == []


# ─────────────────────────────────────────────────────────────────────────
# clear_queue
# ─────────────────────────────────────────────────────────────────────────

def test_clear_queue_removes_file(_tmp_queue_path):
    _tmp_queue_path.write_text('{"tasks": []}', encoding="utf-8")
    assert _tmp_queue_path.exists()
    clear_queue()
    assert not _tmp_queue_path.exists()


def test_clear_queue_no_op_when_file_absent(_tmp_queue_path):
    """Missing file → clear_queue must not raise."""
    assert not _tmp_queue_path.exists()
    clear_queue()   # must not raise


def test_clear_queue_swallows_delete_error(_tmp_queue_path):
    """File exists but can't be deleted (locked by another process) →
    log warning, don't propagate."""
    _tmp_queue_path.write_text('{"tasks": []}', encoding="utf-8")
    with patch.object(queue_persistence.QUEUE_PATH.__class__, "unlink",
                      side_effect=PermissionError("locked")):
        clear_queue()   # must not raise
