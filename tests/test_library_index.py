"""Tests for the local library dedup index."""
from __future__ import annotations

from dataclasses import dataclass

from core.library_index import LibraryIndex, track_key


@dataclass
class _StubRecord:
    """Minimal HistoryManager-record shape the index expects."""
    artist:   str
    title:    str
    status:   str = "done"


class _StubHistory:
    def __init__(self, records):
        self._records = records
    def all(self):
        return self._records


@dataclass
class _StubTrack:
    artist_str: str
    title:      str


def test_normalisation_strips_accents_and_feat():
    a = track_key("Beyoncé", "Halo")
    b = track_key("BEYONCE", "Halo (feat. Someone)")
    assert a == b


def test_normalisation_ignores_case_and_punctuation():
    a = track_key("A-Ha", "Take On Me!")
    b = track_key("a-ha", "take on me")
    assert a == b


def test_normalisation_strips_remix_markers():
    a = track_key("Artist", "Song")
    b = track_key("Artist", "Song (Extended Mix)")
    assert a == b


def test_rebuild_from_history_indexes_only_done():
    hist = _StubHistory([
        _StubRecord("Artist A", "Track 1", "done"),
        _StubRecord("Artist B", "Track 2", "error"),   # skipped
        _StubRecord("Artist C", "Track 3", "done"),
    ])
    idx = LibraryIndex()
    n = idx.rebuild(history_manager=hist)
    assert n == 2
    assert idx.contains("Artist A", "Track 1")
    assert not idx.contains("Artist B", "Track 2")


def test_missing_returns_only_new_tracks():
    hist = _StubHistory([
        _StubRecord("Artist A", "Track 1", "done"),
        _StubRecord("Artist B", "Track 2", "done"),
    ])
    idx = LibraryIndex()
    idx.rebuild(history_manager=hist)

    incoming = [
        _StubTrack("Artist A", "Track 1"),        # already have
        _StubTrack("Artist B", "Track 2 (Remix)"),  # have (remix-stripped)
        _StubTrack("Artist C", "Track 3"),        # new
    ]
    missing = idx.missing(incoming)
    assert len(missing) == 1
    assert missing[0].artist_str == "Artist C"


def test_scan_dir_extracts_artist_title(tmp_path):
    (tmp_path / "Artist X - Some Song.mp3").write_bytes(b"")
    (tmp_path / "Artist Y - Other [FLAC].flac").write_bytes(b"")
    (tmp_path / "not-audio.txt").write_bytes(b"")

    idx = LibraryIndex()
    n = idx.rebuild(extra_scan_dirs=[tmp_path])
    assert n == 2
    assert idx.contains("Artist X", "Some Song")
    assert idx.contains("Artist Y", "Other")
