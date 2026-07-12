"""Tests for ``providers.spotify_provider.SpotifyProvider``.

Spotify is the primary metadata source for most users — playlist
URLs, album lookups, per-track search.  The tests cover the pure
mapping + routing logic without actually hitting the Spotify Web API
(spotipy client is mocked).

Focus:
- ``_track_to_info`` — dict → TrackInfo with cover, year, ISRC, etc.
- Guard on missing/deleted tracks (id-less items in playlists)
- ``search`` / ``search_albums`` — API response → list mapping
- ``get_track`` / ``get_tracks_from_url`` URL routing:
  /track/ /album/ /playlist/ /artist/
- Not-available paths (no credentials) — every method returns [] cleanly
- Album pagination when total > page size
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.spotify_provider import SpotifyProvider


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def bare_provider():
    """SpotifyProvider without spotipy initialization.

    Skips __init__ entirely so no real client is built; hand-sets the
    mocked _sp attribute and _available=True so method bodies run.
    """
    p = SpotifyProvider.__new__(SpotifyProvider)
    p._client_id     = "fake"
    p._client_secret = "fake"
    p._sp            = MagicMock()
    p._available     = True
    return p


@pytest.fixture
def unavailable_provider():
    """Provider whose init failed (no credentials or bad ones)."""
    p = SpotifyProvider.__new__(SpotifyProvider)
    p._client_id     = ""
    p._client_secret = ""
    p._sp            = None
    p._available     = False
    return p


def _spotify_track(**overrides):
    """A minimally realistic Spotify track dict for mocking."""
    base = {
        "id":            "abc123",
        "name":          "Get Lucky",
        "artists":       [{"name": "Daft Punk"}, {"name": "Pharrell Williams"}],
        "album": {
            "name":         "Random Access Memories",
            "release_date": "2013-05-17",
            "artists":      [{"name": "Daft Punk"}],
            "images": [
                {"url": "https://i.scdn.co/large.jpg", "height": 640},
                {"url": "https://i.scdn.co/mid.jpg",   "height": 300},
            ],
            "total_tracks": 13,
        },
        "duration_ms":   369626,
        "external_urls": {"spotify": "https://open.spotify.com/track/abc123"},
        "external_ids":  {"isrc": "USQX91300224"},
        "track_number":  8,
        "disc_number":   1,
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────
# _track_to_info — the mapping heart
# ─────────────────────────────────────────────────────────────────────────

def test_track_to_info_full_shape(bare_provider):
    """A well-formed Spotify track maps every documented TrackInfo field."""
    ti = bare_provider._track_to_info(_spotify_track())
    assert ti is not None
    assert ti.title        == "Get Lucky"
    assert ti.artists      == ["Daft Punk", "Pharrell Williams"]
    assert ti.artist_str   == "Daft Punk, Pharrell Williams"
    assert ti.album        == "Random Access Memories"
    assert ti.album_artist == "Daft Punk"
    assert ti.year         == "2013"
    assert ti.release_date == "2013-05-17"
    assert ti.isrc         == "USQX91300224"
    assert ti.duration_ms  == 369626
    assert ti.source_url   == "https://open.spotify.com/track/abc123"
    assert ti.platform     == "spotify"
    assert ti.track_id     == "abc123"
    assert ti.track_number == 8
    assert ti.disc_number  == 1
    assert ti.total_tracks == 13


def test_track_to_info_picks_largest_cover(bare_provider):
    """Spotify sorts images largest-first; we take images[0]."""
    ti = bare_provider._track_to_info(_spotify_track())
    assert ti.cover_url == "https://i.scdn.co/large.jpg"


def test_track_to_info_none_on_empty_input(bare_provider):
    """Empty dict / None / non-dict → None (playlist items sometimes carry
    tombstones for removed tracks)."""
    assert bare_provider._track_to_info(None) is None
    assert bare_provider._track_to_info({}) is None
    assert bare_provider._track_to_info("garbage") is None


def test_track_to_info_none_when_id_missing(bare_provider):
    """A track dict without 'id' is unavailable (region-blocked, removed)."""
    t = _spotify_track()
    t.pop("id")
    assert bare_provider._track_to_info(t) is None


def test_track_to_info_handles_missing_album_gracefully(bare_provider):
    """Some tracks have a bare album stub — fields become empty strings."""
    t = _spotify_track()
    t["album"] = {}
    ti = bare_provider._track_to_info(t)
    assert ti is not None
    assert ti.album      == ""
    assert ti.cover_url  == ""
    assert ti.year       == ""


def test_track_to_info_filters_empty_artist_names(bare_provider):
    """Some collab tracks carry {'name': ''} entries — skip them."""
    t = _spotify_track()
    t["artists"] = [{"name": "Real Artist"}, {"name": ""}, {}]
    ti = bare_provider._track_to_info(t)
    assert ti.artists == ["Real Artist"]


def test_track_to_info_falls_back_to_unknown_on_missing_title(bare_provider):
    t = _spotify_track()
    t["name"] = ""
    ti = bare_provider._track_to_info(t)
    assert ti.title == "Unknown"


# ─────────────────────────────────────────────────────────────────────────
# Not-available paths
# ─────────────────────────────────────────────────────────────────────────

def test_search_returns_empty_when_unavailable(unavailable_provider):
    assert unavailable_provider.search("anything") == []


def test_get_track_returns_none_when_unavailable(unavailable_provider):
    assert unavailable_provider.get_track("spotify:track:abc") is None


def test_get_tracks_from_url_returns_empty_when_unavailable(unavailable_provider):
    assert unavailable_provider.get_tracks_from_url(
        "https://open.spotify.com/track/abc") == []


# ─────────────────────────────────────────────────────────────────────────
# search
# ─────────────────────────────────────────────────────────────────────────

def test_search_maps_all_results(bare_provider):
    bare_provider._sp.search.return_value = {
        "tracks": {"items": [_spotify_track(id="t1", name="Song 1"),
                             _spotify_track(id="t2", name="Song 2")]}
    }
    out = bare_provider.search("daft punk")
    assert len(out) == 2
    assert out[0].title == "Song 1"
    assert out[1].title == "Song 2"


def test_search_filters_unmapped_tracks(bare_provider):
    """Deleted tracks (missing id) are silently dropped."""
    bad = _spotify_track(); bad.pop("id")
    bare_provider._sp.search.return_value = {
        "tracks": {"items": [_spotify_track(id="ok"), bad]}
    }
    out = bare_provider.search("anything")
    assert len(out) == 1
    assert out[0].track_id == "ok"


def test_search_returns_empty_on_api_exception(bare_provider):
    """A network error / rate limit must not crash the caller."""
    bare_provider._sp.search.side_effect = RuntimeError("Spotify 429")
    assert bare_provider.search("anything") == []


def test_search_caps_limit_at_50(bare_provider):
    """Spotify API rejects limit>50 — we clamp it silently."""
    bare_provider._sp.search.return_value = {"tracks": {"items": []}}
    bare_provider.search("x", limit=200)
    kwargs = bare_provider._sp.search.call_args[1]
    assert kwargs["limit"] == 50


# ─────────────────────────────────────────────────────────────────────────
# search_albums
# ─────────────────────────────────────────────────────────────────────────

def test_search_albums_maps_result(bare_provider):
    bare_provider._sp.search.return_value = {
        "albums": {"items": [{
            "id":            "alb1",
            "name":          "Random Access Memories",
            "artists":       [{"name": "Daft Punk"}],
            "release_date":  "2013",
            "total_tracks":  13,
            "external_urls": {"spotify": "https://open.spotify.com/album/alb1"},
            "images":        [{"url": "https://cover.jpg"}],
        }]}
    }
    out = bare_provider.search_albums("random access")
    assert len(out) == 1
    assert out[0].is_album is True
    assert out[0].track_count == 13
    assert out[0].platform == "spotify"


def test_search_albums_skips_items_without_id(bare_provider):
    bare_provider._sp.search.return_value = {
        "albums": {"items": [{}, {"id": "ok", "name": "X",
                                   "artists": [{"name": "A"}]}]}
    }
    out = bare_provider.search_albums("x")
    assert len(out) == 1


# ─────────────────────────────────────────────────────────────────────────
# URL routing — get_tracks_from_url
# ─────────────────────────────────────────────────────────────────────────

def test_get_tracks_from_url_track_delegates_to_get_track(bare_provider):
    """/track/ URLs route through get_track."""
    with patch.object(bare_provider, "get_track",
                      return_value=MagicMock()) as gt:
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/track/abc123")
    gt.assert_called_once()
    assert len(out) == 1


def test_get_tracks_from_url_track_returns_empty_when_get_track_none(bare_provider):
    with patch.object(bare_provider, "get_track", return_value=None):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/track/abc123")
    assert out == []


def test_get_tracks_from_url_album_lists_all_tracks(bare_provider):
    bare_provider._sp.album.return_value = {
        "name":         "Album Name",
        "release_date": "2020-01-01",
        "artists":      [{"name": "Album Artist"}],
        "images":       [{"url": "https://cover.jpg"}],
        "total_tracks": 2,
        "tracks": {
            "items": [
                {"id": "t1", "name": "Song 1",
                 "artists": [{"name": "Artist"}], "duration_ms": 200000,
                 "external_urls": {"spotify": "https://.../t1"},
                 "track_number": 1, "disc_number": 1},
                {"id": "t2", "name": "Song 2",
                 "artists": [{"name": "Artist"}], "duration_ms": 210000,
                 "external_urls": {"spotify": "https://.../t2"},
                 "track_number": 2, "disc_number": 1},
            ],
            "next": None,
        },
    }
    with patch("providers.spotify_provider.extract_spotify_id",
               return_value="alb1"):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/album/alb1")
    assert len(out) == 2
    assert out[0].album      == "Album Name"
    assert out[0].year       == "2020"
    assert out[0].cover_url  == "https://cover.jpg"
    assert out[0].total_tracks == 2


def test_get_tracks_from_url_playlist_paginates(bare_provider):
    """When Spotify returns 'next', follow it until the tracks are exhausted."""
    page1 = {
        "items": [{"track": _spotify_track(id="p1")}],
        "next":  "https://.../page2",
    }
    page2 = {
        "items": [{"track": _spotify_track(id="p2")}],
        "next":  None,
    }
    bare_provider._sp.playlist_tracks.side_effect = [page1, page2]
    with patch("providers.spotify_provider.extract_spotify_id",
               return_value="pl1"):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/playlist/pl1")
    assert len(out) == 2
    assert out[0].track_id == "p1"
    assert out[1].track_id == "p2"


def test_get_tracks_from_url_playlist_stops_on_empty_batch(bare_provider):
    """Guard against infinite loops when Spotify returns 'next' with []."""
    empty_page = {"items": [], "next": "still/has/next"}
    bare_provider._sp.playlist_tracks.return_value = empty_page
    with patch("providers.spotify_provider.extract_spotify_id",
               return_value="pl1"):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/playlist/pl1")
    assert out == []
    # Should only have called once — empty batch → break.
    assert bare_provider._sp.playlist_tracks.call_count == 1


def test_get_tracks_from_url_playlist_skips_none_tracks(bare_provider):
    """Playlist items with track=None (removed tracks) are dropped."""
    bare_provider._sp.playlist_tracks.return_value = {
        "items": [
            {"track": _spotify_track(id="ok")},
            {"track": None},
            {"track": _spotify_track(id="ok2")},
        ],
        "next": None,
    }
    with patch("providers.spotify_provider.extract_spotify_id",
               return_value="pl1"):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/playlist/pl1")
    assert len(out) == 2


def test_get_tracks_from_url_artist_returns_top_tracks(bare_provider):
    bare_provider._sp.artist_top_tracks.return_value = {
        "tracks": [_spotify_track(id="top1"), _spotify_track(id="top2")]
    }
    with patch("providers.spotify_provider.extract_spotify_id",
               return_value="artist1"):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/artist/artist1")
    assert len(out) == 2


def test_get_tracks_from_url_unknown_shape_returns_empty(bare_provider):
    """A Spotify URL variant we don't recognise → empty list, no crash."""
    out = bare_provider.get_tracks_from_url(
        "https://open.spotify.com/user/xxxx/wrapped")
    assert out == []


def test_get_tracks_from_url_catches_api_error(bare_provider):
    """An unhandled spotipy exception must degrade to [] silently."""
    bare_provider._sp.album.side_effect = RuntimeError("500 backend error")
    with patch("providers.spotify_provider.extract_spotify_id",
               return_value="alb1"):
        out = bare_provider.get_tracks_from_url(
            "https://open.spotify.com/album/alb1")
    assert out == []


# ─────────────────────────────────────────────────────────────────────────
# name / available properties
# ─────────────────────────────────────────────────────────────────────────

def test_name_property(bare_provider):
    assert bare_provider.name == "Spotify"


def test_available_reflects_init_state(bare_provider, unavailable_provider):
    assert bare_provider.available is True
    assert unavailable_provider.available is False
