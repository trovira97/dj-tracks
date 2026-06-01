"""Unit tests for utils.file_utils."""
from __future__ import annotations

import pytest

from utils.file_utils import (
    build_output_path, ensure_dir, format_filesize, get_unique_path,
)


class TestFormatFilesize:
    @pytest.mark.parametrize("size,expected", [
        (0,           "0.0 B"),
        (512,         "512.0 B"),
        (1024,        "1.0 KB"),
        (1536,        "1.5 KB"),
        (1_048_576,   "1.0 MB"),
        (10_485_760,  "10.0 MB"),
        (1_073_741_824, "1.0 GB"),
    ])
    def test_formats(self, size, expected):
        assert format_filesize(size) == expected


class TestGetUniquePath:
    def test_returns_original_if_not_exists(self, tmp_path):
        p = tmp_path / "nope.mp3"
        assert get_unique_path(p) == p

    def test_appends_counter_on_collision(self, tmp_path):
        p = tmp_path / "track.mp3"
        p.touch()
        assert get_unique_path(p).name == "track (1).mp3"

    def test_skips_existing_counters(self, tmp_path):
        (tmp_path / "track.mp3").touch()
        (tmp_path / "track (1).mp3").touch()
        (tmp_path / "track (2).mp3").touch()
        assert get_unique_path(tmp_path / "track.mp3").name == "track (3).mp3"


class TestBuildOutputPath:
    def test_creates_parent_dirs(self, tmp_path):
        p = build_output_path(str(tmp_path), "Artist", "Album", "Track", "mp3")
        assert p.parent.exists()
        assert p.suffix == ".mp3"
        assert p.name == "Artist - Track.mp3"

    def test_sanitises_components(self, tmp_path):
        p = build_output_path(str(tmp_path), "Bad:Artist", "Bad/Album", "Bad*Title", "mp3")
        # Look only at the components added by build_output_path,
        # not the base path (which may contain ':' on Windows like 'C:\\').
        relative = p.relative_to(tmp_path)
        s = str(relative)
        for bad in r'*?"<>|':
            assert bad not in s, f"Illegal char {bad!r} leaked into {s!r}"
        # The ':' character must not appear in any sanitised component name.
        for part in relative.parts:
            assert ":" not in part, f"Colon leaked into part {part!r}"

    def test_custom_structure(self, tmp_path):
        p = build_output_path(
            str(tmp_path), "Artist", "Album", "Track", "flac",
            structure="{artist}/{title}",
        )
        assert p.relative_to(tmp_path) .as_posix() == "Artist/Track.flac"


class TestEnsureDir:
    def test_creates_missing(self, tmp_path):
        d = tmp_path / "a" / "b" / "c"
        result = ensure_dir(d)
        assert result.exists() and result.is_dir()

    def test_idempotent(self, tmp_path):
        d = tmp_path / "x"
        ensure_dir(d)
        ensure_dir(d)   # second call must not raise
        assert d.exists()
