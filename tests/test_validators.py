"""Unit tests for utils.validators."""
from __future__ import annotations

import pytest

from utils.validators import (
    ContentType, Platform,
    detect_content_type, detect_platform,
    extract_spotify_id, is_valid_url,
    sanitize_filename,
)


class TestSanitizeFilename:
    def test_removes_illegal_chars(self):
        # Illegal chars: \ / : * ? " < > |
        result = sanitize_filename('a:b/c*d<e>f"g|h?i\\j')
        for bad in r'\/:*?"<>|':
            assert bad not in result
        assert result == "abcdefghij"

    def test_empty_falls_back_to_unknown(self):
        assert sanitize_filename("") == "unknown"
        assert sanitize_filename("   ") == "unknown"
        assert sanitize_filename("...") == "unknown"

    def test_truncates_to_max_length(self):
        long_name = "a" * 500
        assert len(sanitize_filename(long_name, max_length=100)) == 100

    @pytest.mark.parametrize("reserved", [
        "CON", "PRN", "AUX", "NUL",
        "COM1", "COM9", "LPT1", "LPT9",
    ])
    def test_windows_reserved_names_prefixed(self, reserved):
        assert sanitize_filename(reserved) == f"_{reserved}"
        # case-insensitive
        assert sanitize_filename(reserved.lower()) == f"_{reserved.lower()}"

    def test_preserves_unicode(self):
        assert sanitize_filename("Café — Niño") == "Café — Niño"


class TestDetectPlatform:
    @pytest.mark.parametrize("url,expected", [
        ("https://open.spotify.com/track/abc",         Platform.SPOTIFY),
        ("https://spotify.com/playlist/xyz",           Platform.SPOTIFY),
        ("https://music.apple.com/es/album/x/123",     Platform.APPLE_MUSIC),
        ("https://music.apple.com/us/playlist/abc",    Platform.APPLE_MUSIC),
        ("https://soundcloud.com/artist/track",        Platform.SOUNDCLOUD),
        ("https://www.soundcloud.com/user",            Platform.SOUNDCLOUD),
        ("https://youtube.com/watch?v=xyz",            Platform.UNKNOWN),
        ("not a url",                                  Platform.UNKNOWN),
    ])
    def test_detects(self, url, expected):
        assert detect_platform(url) == expected


class TestDetectContentType:
    @pytest.mark.parametrize("url,expected", [
        ("https://open.spotify.com/track/abc",    ContentType.TRACK),
        ("https://open.spotify.com/album/abc",    ContentType.ALBUM),
        ("https://open.spotify.com/playlist/abc", ContentType.PLAYLIST),
        ("https://open.spotify.com/artist/abc",   ContentType.ARTIST),
        ("https://spotify.com/intl-es/track/abc", ContentType.TRACK),
        ("https://music.apple.com/es/album/x/123?i=456", ContentType.TRACK),
        ("https://music.apple.com/es/album/x/123",       ContentType.ALBUM),
        ("https://music.apple.com/es/artist/x/123",      ContentType.ARTIST),
        ("https://example.com",                          ContentType.UNKNOWN),
    ])
    def test_detects(self, url, expected):
        assert detect_content_type(url) == expected


class TestIsValidUrl:
    @pytest.mark.parametrize("url,expected", [
        ("http://example.com",  True),
        ("https://example.com", True),
        ("ftp://example.com",   False),
        ("example.com",         False),
        ("",                    False),
    ])
    def test_validates(self, url, expected):
        assert is_valid_url(url) is expected


class TestExtractSpotifyId:
    def test_extracts_track_id(self):
        assert extract_spotify_id(
            "https://open.spotify.com/track/3n3Ppam7vgaVa1iaRUIOKE"
        ) == "3n3Ppam7vgaVa1iaRUIOKE"

    def test_handles_intl_prefix(self):
        assert extract_spotify_id(
            "https://open.spotify.com/intl-es/track/3n3Ppam7vgaVa1iaRUIOKE"
        ) == "3n3Ppam7vgaVa1iaRUIOKE"

    def test_returns_none_for_invalid(self):
        assert extract_spotify_id("https://example.com") is None
        assert extract_spotify_id("not-a-url") is None
