"""Unit tests for providers.bandcamp_provider (offline, no network)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.bandcamp_provider import BandcampProvider


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────────

@pytest.fixture
def provider():
    return BandcampProvider()


def _mock_response(json_data: dict):
    resp = MagicMock()
    resp.json.return_value = json_data
    resp.raise_for_status = MagicMock()
    return resp


# ─────────────────────────────────────────────────────────────────────────────
# Provider basics
# ─────────────────────────────────────────────────────────────────────────────

class TestBandcampProviderBasics:
    def test_name(self, provider):
        assert provider.name == "Bandcamp"

    def test_always_available(self, provider):
        assert provider.available is True


# ─────────────────────────────────────────────────────────────────────────────
# Search
# ─────────────────────────────────────────────────────────────────────────────

class TestSearch:
    def test_empty_query_returns_empty(self, provider):
        assert provider.search("") == []
        assert provider.search("   ") == []

    def test_parses_results(self, provider):
        payload = {
            "auto": {
                "results": [
                    {
                        "type": "t",
                        "id": 12345,
                        "name": "Midnight Drive",
                        "band_name": "Neon Cars",
                        "album_name": "Synthwave EP",
                        "img": "https://f4.bcbits.com/img/a123_10.jpg",
                        "item_url_path": "https://neoncars.bandcamp.com/track/midnight-drive",
                    },
                    {
                        "type": "t",
                        "name": "Glow",
                        "band_name": "Synth Lord",
                        "img": 456789,                     # numeric ID form
                        "item_url_path": "https://synthlord.bandcamp.com/track/glow",
                    },
                ]
            }
        }
        with patch.object(provider._session, "post", return_value=_mock_response(payload)):
            results = provider.search("synthwave")

        assert len(results) == 2
        assert results[0].title    == "Midnight Drive"
        assert results[0].artists  == ["Neon Cars"]
        assert results[0].album    == "Synthwave EP"
        assert results[0].platform == "bandcamp"
        assert results[0].source_url == "https://neoncars.bandcamp.com/track/midnight-drive"
        assert results[0].cover_url.startswith("https://f4.bcbits.com/")

        # Numeric img IDs are converted to full URLs at original resolution (_0).
        assert "f4.bcbits.com/img/a456789_0" in results[1].cover_url

    def test_skips_non_track_items(self, provider):
        payload = {
            "auto": {
                "results": [
                    {"type": "a", "name": "Album Item",  "band_name": "X"},  # album, skip
                    {"type": "b", "name": "Band Item",   "band_name": "Y"},  # band, skip
                    {"type": "t", "name": "Track Item",  "band_name": "Z",
                     "item_url_path": "https://z.bandcamp.com/track/track-item"},
                ]
            }
        }
        with patch.object(provider._session, "post", return_value=_mock_response(payload)):
            results = provider.search("anything")
        assert len(results) == 1
        assert results[0].title == "Track Item"

    def test_respects_limit(self, provider):
        payload = {
            "auto": {
                "results": [
                    {"type": "t", "name": f"T{i}", "band_name": "Artist",
                     "item_url_path": f"https://a.bandcamp.com/track/t{i}"}
                    for i in range(50)
                ]
            }
        }
        with patch.object(provider._session, "post", return_value=_mock_response(payload)):
            results = provider.search("x", limit=5)
        assert len(results) == 5

    def test_network_error_returns_empty(self, provider):
        with patch.object(provider._session, "post", side_effect=Exception("boom")):
            assert provider.search("anything") == []

    def test_malformed_response_returns_empty(self, provider):
        with patch.object(provider._session, "post", return_value=_mock_response({})):
            assert provider.search("x") == []


# ─────────────────────────────────────────────────────────────────────────────
# URL resolution
# ─────────────────────────────────────────────────────────────────────────────

class TestGetTracksFromUrl:
    def test_track_url(self, provider):
        url = "https://artist.bandcamp.com/track/some-song"
        tracks = provider.get_tracks_from_url(url)
        assert len(tracks) == 1
        assert tracks[0].source_url == url
        assert tracks[0].platform   == "bandcamp"

    def test_album_url(self, provider):
        url = "https://artist.bandcamp.com/album/some-album"
        tracks = provider.get_tracks_from_url(url)
        assert len(tracks) == 1
        assert tracks[0].source_url == url

    def test_unknown_url(self, provider):
        assert provider.get_tracks_from_url("https://example.com") == []


class TestGetTrack:
    def test_url_returns_placeholder(self, provider):
        info = provider.get_track("https://artist.bandcamp.com/track/some-song")
        assert info is not None
        assert info.platform == "bandcamp"

    def test_bare_id_returns_none(self, provider):
        assert provider.get_track("12345") is None
