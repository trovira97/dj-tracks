"""Tests for :class:`~core.search_manager.SearchManager` — the
multi-platform orchestrator.

Focus areas:
- Deduplication logic (case-insensitive artist|title, album/track namespaces)
- URL resolution routing (delegates to the correct provider by platform)
- Stub fallback when no provider matches
"""
from __future__ import annotations

from unittest.mock import MagicMock

from core.search_manager import SearchManager
from providers import TrackInfo
from utils.validators import Platform


# ── Deduplication ────────────────────────────────────────────────────────

def _track(artist, title, *, is_album=False):
    return TrackInfo(title=title, artists=[artist], is_album=is_album)


def test_dedup_removes_exact_duplicates():
    inp = [_track("A", "T"), _track("A", "T")]
    assert len(SearchManager._deduplicate(inp)) == 1


def test_dedup_is_case_insensitive():
    inp = [_track("Artist", "Track"),
           _track("ARTIST", "TRACK"),
           _track("artist", "track")]
    out = SearchManager._deduplicate(inp)
    assert len(out) == 1
    # First occurrence is kept.
    assert out[0].artists[0] == "Artist"


def test_dedup_keeps_different_titles():
    inp = [_track("Artist", "Song 1"), _track("Artist", "Song 2")]
    assert len(SearchManager._deduplicate(inp)) == 2


def test_dedup_keeps_different_artists():
    inp = [_track("A", "Same Title"), _track("B", "Same Title")]
    assert len(SearchManager._deduplicate(inp)) == 2


def test_dedup_keeps_album_and_track_of_same_name():
    """An album 'Rumours' and a track 'Rumours' are different entities
    — the tag prefix in the key keeps them separate."""
    inp = [_track("Fleetwood Mac", "Rumours", is_album=True),
           _track("Fleetwood Mac", "Rumours", is_album=False)]
    out = SearchManager._deduplicate(inp)
    assert len(out) == 2


# ── URL resolution ───────────────────────────────────────────────────────

def test_resolve_url_unknown_returns_empty():
    sm = SearchManager()
    assert sm.resolve_url("https://random-place.example/song") == []


def test_resolve_url_delegates_to_matching_provider():
    """Given a Spotify URL, only the Spotify provider is called."""
    spotify_stub = MagicMock()
    spotify_stub.get_tracks_from_url.return_value = [_track("A", "T")]

    sm = SearchManager()
    sm._providers[Platform.SPOTIFY] = spotify_stub

    result = sm.resolve_url("https://open.spotify.com/track/abc123")
    assert len(result) == 1
    spotify_stub.get_tracks_from_url.assert_called_once()


def test_resolve_url_returns_stub_when_provider_absent():
    """Detected platform (e.g. Bandcamp) but no provider registered:
    return a minimal stub so the downloader can still try yt-dlp."""
    sm = SearchManager()
    # Ensure Bandcamp is NOT in the providers map.
    sm._providers.pop(Platform.BANDCAMP, None)

    result = sm.resolve_url("https://artist.bandcamp.com/track/some-song")
    assert len(result) == 1
    assert result[0].source_url.startswith("https://")
    # The stub must carry the platform so the downloader can decide behaviour.
    assert result[0].platform == "bandcamp"


# ── Search: single-platform delegation ───────────────────────────────────

def test_search_single_platform_delegates():
    apple_stub = MagicMock()
    apple_stub.search.return_value = [_track("A", "T1"), _track("A", "T2")]

    sm = SearchManager()
    sm._providers[Platform.APPLE_MUSIC] = apple_stub

    results = sm.search("query", platform=Platform.APPLE_MUSIC, limit=10)
    apple_stub.search.assert_called_once()
    assert len(results) == 2


def test_search_missing_provider_returns_empty():
    sm = SearchManager()
    sm._providers.pop(Platform.SPOTIFY, None)
    assert sm.search("query", platform=Platform.SPOTIFY) == []


# ── update_provider / provider_for ──────────────────────────────────────

def test_update_provider_replaces_at_runtime():
    sm = SearchManager()
    new_apple = MagicMock()
    sm.update_provider(Platform.APPLE_MUSIC, new_apple)
    assert sm.provider_for(Platform.APPLE_MUSIC) is new_apple


def test_provider_for_absent_returns_none():
    sm = SearchManager()
    sm._providers.pop(Platform.SPOTIFY, None)
    assert sm.provider_for(Platform.SPOTIFY) is None
