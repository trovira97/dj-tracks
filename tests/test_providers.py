"""Unit tests for the providers package — TrackInfo, AudioMetadata,
and SearchManager deduplication (no network calls)."""
from __future__ import annotations

import pytest

from core.search_manager import SearchManager
from metadata.metadata_reader import AudioMetadata
from providers import TrackInfo


class TestTrackInfo:
    def test_artist_str(self):
        assert TrackInfo("T", ["A", "B"]).artist_str == "A, B"

    def test_artist_str_single(self):
        assert TrackInfo("T", ["Solo"]).artist_str == "Solo"

    @pytest.mark.parametrize("ms,expected", [
        (227_000, "3:47"),
        (60_000,  "1:00"),
        (5_000,   "0:05"),
        (0,       "--:--"),
    ])
    def test_duration_str(self, ms, expected):
        assert TrackInfo("T", ["A"], duration_ms=ms).duration_str == expected

    def test_extra_field_defaults_to_empty_dict(self):
        t1 = TrackInfo("T", ["A"])
        t2 = TrackInfo("T", ["A"])
        t1.extra["key"] = "value"
        # Extras must not leak between instances.
        assert t2.extra == {}, f"Mutable default leaked: {t2.extra}"

    def test_new_metadata_fields_default_safely(self):
        """New fields added in v2.2 must default to safe falsy values."""
        t = TrackInfo("T", ["A"])
        assert t.album_artist == ""
        assert t.release_date == ""
        assert t.track_number == 0
        assert t.disc_number  == 0
        assert t.total_tracks == 0

    def test_full_metadata_construction(self):
        t = TrackInfo(
            title="Song", artists=["A1", "A2"],
            album="Album", album_artist="A1",
            year="2024", release_date="2024-03-15",
            track_number=5, disc_number=1, total_tracks=12,
        )
        assert t.album_artist == "A1"
        assert t.release_date == "2024-03-15"
        assert t.track_number == 5
        assert t.disc_number  == 1
        assert t.total_tracks == 12


class TestAudioMetadata:
    def test_artists_default_is_isolated_list(self):
        m1 = AudioMetadata()
        m2 = AudioMetadata()
        m1.artists.append("X")
        assert m2.artists == [], f"Mutable default leaked: {m2.artists}"

    def test_artist_str_joins(self):
        m = AudioMetadata(artists=["A", "B", "C"])
        assert m.artist_str == "A, B, C"


class TestSearchManagerDedup:
    def test_removes_duplicates_by_artist_title(self):
        t1 = TrackInfo("Song A", ["Artist"], platform="spotify")
        t2 = TrackInfo("Song A", ["Artist"], platform="applemusic")  # dup
        t3 = TrackInfo("Song B", ["Artist"], platform="spotify")
        result = SearchManager._deduplicate([t1, t2, t3])
        assert len(result) == 2
        assert result[0] is t1   # first occurrence wins
        assert result[1] is t3

    def test_case_insensitive(self):
        t1 = TrackInfo("song", ["artist"], platform="spotify")
        t2 = TrackInfo("SONG", ["ARTIST"], platform="applemusic")
        assert len(SearchManager._deduplicate([t1, t2])) == 1

    def test_empty_input(self):
        assert SearchManager._deduplicate([]) == []
