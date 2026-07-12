"""Tests for ``providers.applemusic_provider``.

Apple Music via the public iTunes Search API — no auth needed, so
this provider is the simplest of the four to test.  The value-adds
worth guarding: the artwork URL upgrade (100×100 → 3000×3000 for
tracks, 1200×1200 for albums), the two id-extraction patterns
(?i=NNN for songs, /album/name/NNN for albums), and the routing in
``get_tracks_from_url`` which falls back to a name search when
the URL has no id.

Focus:
- ``_item_to_info`` — mapping, artwork upgrade, fallbacks for missing
  trackName / artistName / collectionArtistName
- ``_extract_apple_id`` — both regex patterns, precedence, no-match
- ``search`` / ``search_albums`` — filter by wrapperType
- ``get_track`` — URL vs ID input, empty-result guard
- ``get_tracks_from_url`` — song (?i=), album by id, name-search
  fallback for artist-slug URLs
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.applemusic_provider import AppleMusicProvider


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def provider():
    """Provider with a mocked HTTP Session."""
    p = AppleMusicProvider()
    p._session = MagicMock()
    return p


def _itunes_track(**overrides):
    """A minimally realistic iTunes track item."""
    base = {
        "wrapperType":          "track",
        "trackId":              12345,
        "trackName":            "Get Lucky",
        "artistName":           "Daft Punk",
        "collectionName":       "Random Access Memories",
        "collectionArtistName": "Daft Punk",
        "primaryGenreName":     "Electronic",
        "artworkUrl100":        "https://is1.mzstatic.com/image/thumb/x/100x100bb.jpg",
        "trackViewUrl":         "https://music.apple.com/es/album/name/1?i=12345",
        "collectionViewUrl":    "https://music.apple.com/es/album/name/1",
        "trackTimeMillis":      369626,
        "releaseDate":          "2013-05-17T07:00:00Z",
        "trackNumber":          8,
        "discNumber":           1,
        "trackCount":           13,
    }
    base.update(overrides)
    return base


def _itunes_album(**overrides):
    base = {
        "wrapperType":       "collection",
        "collectionId":      777,
        "collectionName":    "Random Access Memories",
        "artistName":        "Daft Punk",
        "artworkUrl100":     "https://is1.mzstatic.com/image/thumb/x/100x100bb.jpg",
        "collectionViewUrl": "https://music.apple.com/es/album/name/777",
        "releaseDate":       "2013-05-17T07:00:00Z",
        "trackCount":        13,
    }
    base.update(overrides)
    return base


# ─────────────────────────────────────────────────────────────────────────
# _item_to_info
# ─────────────────────────────────────────────────────────────────────────

def test_item_to_info_full_shape(provider):
    ti = provider._item_to_info(_itunes_track())
    assert ti.title        == "Get Lucky"
    assert ti.artists      == ["Daft Punk"]
    assert ti.album        == "Random Access Memories"
    assert ti.album_artist == "Daft Punk"
    assert ti.year         == "2013"
    assert ti.release_date == "2013-05-17T07:00:00Z"
    assert ti.genre        == "Electronic"
    assert ti.duration_ms  == 369626
    assert ti.platform     == "applemusic"
    assert ti.track_id     == "12345"
    assert ti.track_number == 8
    assert ti.disc_number  == 1
    assert ti.total_tracks == 13


def test_item_to_info_upgrades_artwork_to_3000(provider):
    """iTunes serves 100×100 by default; the CDN accepts any resolution
    via string substitution — 3000×3000bb is the highest reliably served."""
    t = _itunes_track(
        artworkUrl100="https://is1.mzstatic.com/image/thumb/abc/100x100bb.jpg")
    ti = provider._item_to_info(t)
    assert "3000x3000bb" in ti.cover_url
    assert "100x100" not in ti.cover_url


def test_item_to_info_handles_missing_bb_suffix(provider):
    """Some older items only have '100x100' without the 'bb' background."""
    t = _itunes_track(
        artworkUrl100="https://is1.mzstatic.com/image/thumb/abc/100x100.jpg")
    ti = provider._item_to_info(t)
    assert "3000x3000bb" in ti.cover_url


def test_item_to_info_falls_back_to_collection_name_when_no_track_name(provider):
    """Collection-level results have collectionName but no trackName."""
    t = _itunes_track()
    t.pop("trackName")
    ti = provider._item_to_info(t)
    assert ti.title == "Random Access Memories"   # collectionName wins


def test_item_to_info_defaults_artist_to_unknown(provider):
    t = _itunes_track(artistName=None)
    ti = provider._item_to_info(t)
    assert ti.artists == ["Unknown"]


def test_item_to_info_uses_artist_when_no_collection_artist(provider):
    """Some tracks lack collectionArtistName (single-artist albums);
    fall back to the artist name."""
    t = _itunes_track()
    t.pop("collectionArtistName")
    ti = provider._item_to_info(t)
    assert ti.album_artist == "Daft Punk"


def test_item_to_info_source_url_prefers_track_view_over_collection(provider):
    """When both are present, trackViewUrl (the song's page) wins."""
    ti = provider._item_to_info(_itunes_track())
    assert "?i=12345" in ti.source_url or ti.source_url.endswith("i=12345")


# ─────────────────────────────────────────────────────────────────────────
# _extract_apple_id
# ─────────────────────────────────────────────────────────────────────────

def test_extract_apple_id_from_song_url(provider):
    """Song URLs carry the trackId in ?i=NNN."""
    aid = provider._extract_apple_id(
        "https://music.apple.com/es/album/random-access-memories/1440833098?i=1440833102")
    assert aid == "1440833102"


def test_extract_apple_id_from_album_url(provider):
    """Album URLs put the collectionId as the last path segment."""
    aid = provider._extract_apple_id(
        "https://music.apple.com/es/album/random-access-memories/1440833098")
    assert aid == "1440833098"


def test_extract_apple_id_from_artist_url(provider):
    aid = provider._extract_apple_id(
        "https://music.apple.com/es/artist/daft-punk/5468295")
    assert aid == "5468295"


def test_extract_apple_id_playlist_alphanumeric_returns_none(provider):
    """Apple Music playlist IDs use a 'pl.xxxxx' alphanumeric format, not
    numeric — the id-extraction regex is deliberately numeric-only, so
    playlists don't resolve.  Documented behaviour, not a bug."""
    aid = provider._extract_apple_id(
        "https://music.apple.com/es/playlist/dj-picks/pl.abc123def456")
    assert aid is None


def test_extract_apple_id_prefers_i_param_over_path_id(provider):
    """A song URL has BOTH the album id in the path and the track id in ?i=.
    We want the ?i= (song), not the album id."""
    aid = provider._extract_apple_id(
        "https://music.apple.com/es/album/foo/111?i=222")
    assert aid == "222"


def test_extract_apple_id_no_match_returns_none(provider):
    """A URL that's neither an album/artist/playlist path nor has ?i=."""
    assert provider._extract_apple_id("https://music.apple.com/browse") is None


# ─────────────────────────────────────────────────────────────────────────
# search
# ─────────────────────────────────────────────────────────────────────────

def _mock_json_response(provider, payload, ok=True):
    """Hook the mocked Session.get to return a specific JSON payload."""
    r = MagicMock()
    r.json.return_value = payload
    if ok:
        r.raise_for_status = MagicMock()
    else:
        r.raise_for_status = MagicMock(side_effect=Exception("HTTP 5xx"))
    provider._session.get.return_value = r
    return r


def test_search_maps_track_results(provider):
    _mock_json_response(provider, {"results": [_itunes_track(),
                                                _itunes_track(trackId=2)]})
    out = provider.search("daft punk")
    assert len(out) == 2
    assert out[0].platform == "applemusic"


def test_search_filters_non_track_wrappers(provider):
    """Search returns tracks + collections mixed; we only keep tracks."""
    _mock_json_response(provider, {"results": [
        _itunes_track(),
        _itunes_album(),          # dropped
        _itunes_track(trackId=3),
    ]})
    out = provider.search("query")
    assert len(out) == 2   # album dropped


def test_search_returns_empty_on_http_error(provider):
    """iTunes 5xx / network drop → [] silently, no propagation."""
    provider._session.get.side_effect = Exception("network")
    assert provider.search("anything") == []


def test_search_passes_correct_params(provider):
    """entity=song + media=music — otherwise iTunes returns podcasts."""
    _mock_json_response(provider, {"results": []})
    provider.search("query", limit=25)
    params = provider._session.get.call_args[1]["params"]
    assert params["entity"] == "song"
    assert params["media"]  == "music"
    assert params["limit"]  == 25
    assert params["term"]   == "query"


# ─────────────────────────────────────────────────────────────────────────
# search_albums
# ─────────────────────────────────────────────────────────────────────────

def test_search_albums_maps_collections(provider):
    _mock_json_response(provider, {"results": [_itunes_album(),
                                                _itunes_album(collectionId=2)]})
    out = provider.search_albums("random access")
    assert len(out) == 2
    assert all(a.is_album for a in out)
    assert out[0].track_count == 13


def test_search_albums_filters_non_collection_wrappers(provider):
    _mock_json_response(provider, {"results": [_itunes_track(),
                                                _itunes_album()]})
    out = provider.search_albums("query")
    assert len(out) == 1
    assert out[0].is_album


def test_search_albums_upgrades_artwork_to_1200(provider):
    """Albums use the smaller 1200×1200 upgrade instead of 3000×3000
    to save bandwidth on grid views."""
    _mock_json_response(provider, {"results": [_itunes_album(
        artworkUrl100="https://is1.mzstatic.com/image/thumb/x/100x100bb.jpg"
    )]})
    out = provider.search_albums("query")
    assert "1200x1200bb" in out[0].cover_url


def test_search_albums_empty_on_error(provider):
    provider._session.get.side_effect = Exception("network")
    assert provider.search_albums("anything") == []


# ─────────────────────────────────────────────────────────────────────────
# get_track
# ─────────────────────────────────────────────────────────────────────────

def test_get_track_from_url_extracts_id_and_looks_up(provider):
    _mock_json_response(provider, {"results": [_itunes_track()]})
    ti = provider.get_track(
        "https://music.apple.com/es/album/foo/111?i=12345")
    assert ti is not None
    assert ti.title == "Get Lucky"


def test_get_track_from_bare_id(provider):
    """Bare numeric ID goes straight to the lookup endpoint."""
    _mock_json_response(provider, {"results": [_itunes_track(trackId=999)]})
    ti = provider.get_track("999")
    assert ti is not None
    params = provider._session.get.call_args[1]["params"]
    assert params["id"] == "999"


def test_get_track_returns_none_when_url_has_no_id(provider):
    """No ?i= and no /album/name/NNN pattern → can't extract, return None."""
    assert provider.get_track("https://music.apple.com/browse") is None


def test_get_track_returns_none_when_lookup_empty(provider):
    """iTunes lookup returned {} — no items, return None."""
    _mock_json_response(provider, {"results": []})
    assert provider.get_track("999") is None


def test_get_track_returns_none_on_http_error(provider):
    provider._session.get.side_effect = Exception("500")
    assert provider.get_track("999") is None


# ─────────────────────────────────────────────────────────────────────────
# get_tracks_from_url
# ─────────────────────────────────────────────────────────────────────────

def test_get_tracks_from_url_song_delegates_to_get_track(provider):
    """URL with ?i=NNN → single song via get_track."""
    with patch.object(provider, "get_track",
                      return_value=MagicMock()) as gt:
        out = provider.get_tracks_from_url(
            "https://music.apple.com/es/album/foo/111?i=222")
    gt.assert_called_once()
    assert len(out) == 1


def test_get_tracks_from_url_song_returns_empty_when_get_track_none(provider):
    with patch.object(provider, "get_track", return_value=None):
        out = provider.get_tracks_from_url(
            "https://music.apple.com/es/album/foo/111?i=222")
    assert out == []


def test_get_tracks_from_url_album_returns_track_list(provider):
    """Album lookup returns first item = album (collection), rest = tracks."""
    _mock_json_response(provider, {"results": [
        _itunes_album(),                     # first item = album, skipped
        _itunes_track(trackId=1, trackName="S1"),
        _itunes_track(trackId=2, trackName="S2"),
    ]})
    out = provider.get_tracks_from_url(
        "https://music.apple.com/es/album/rand/1440833098")
    assert len(out) == 2
    assert {t.title for t in out} == {"S1", "S2"}


def test_get_tracks_from_url_album_uses_entity_song_param(provider):
    """The lookup call must include entity=song, otherwise iTunes returns
    only the album row."""
    _mock_json_response(provider, {"results": [_itunes_album()]})
    provider.get_tracks_from_url(
        "https://music.apple.com/es/album/rand/1440833098")
    params = provider._session.get.call_args[1]["params"]
    assert params["entity"] == "song"


def test_get_tracks_from_url_fallback_to_name_search_when_no_id(provider):
    """Some Apple Music URLs don't include a numeric id (rare beta URLs
    or manual shortenings) — extract the slug and search by name.
    The slug regex requires a TRAILING slash, so the URL must end with '/'."""
    _mock_json_response(provider, {"results": [_itunes_track()]})
    out = provider.get_tracks_from_url(
        "https://music.apple.com/es/artist/daft-punk/")
    # Search was called (name-based) → we get results.
    assert len(out) == 1


def test_get_tracks_from_url_returns_empty_when_no_id_and_no_slug(provider):
    """No id, no slug → give up."""
    out = provider.get_tracks_from_url("https://music.apple.com/browse")
    assert out == []


def test_get_tracks_from_url_empty_on_http_error(provider):
    provider._session.get.side_effect = Exception("network")
    out = provider.get_tracks_from_url(
        "https://music.apple.com/es/album/rand/1440833098")
    assert out == []


# ─────────────────────────────────────────────────────────────────────────
# name property
# ─────────────────────────────────────────────────────────────────────────

def test_name_property(provider):
    assert provider.name == "Apple Music"
