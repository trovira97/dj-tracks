"""Tests for ``providers.soundcloud_provider``.

SoundCloud is the provider hit by the O.B.I. 404 bug earlier — it's
also the one whose ``client_id`` has to be scraped from
SoundCloud's JavaScript bundles because they don't offer a public
API key.  These tests exercise both the client_id auto-extraction
and the resource-kind routing (track vs playlist vs user).

Focus:
- ``_valid_id`` — the regex gate on manual client_id config
- ``_ensure_client_id`` — scraping fallback:
  * short-circuit when a valid id is already set
  * walks the JS asset list, keeps the first match
  * bails cleanly when SoundCloud changes their asset structure
  * handles network errors
- ``_to_info`` — track mapping including the "Artist - Title"
  convention and the artwork ``-large`` → ``-original`` upgrade
- ``search`` / ``search_albums`` / ``get_track`` /
  ``get_tracks_from_url`` — all routing paths with mocked ``_api``
- Playlist hydration: SoundCloud returns some tracks title-less;
  they must be re-fetched via ``/tracks?ids=...``
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from providers.soundcloud_provider import SoundCloudProvider


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture
def provider():
    """Provider with a mocked HTTP Session and a pre-set valid client_id
    (skips scraping in most tests — that path has its own dedicated tests)."""
    p = SoundCloudProvider(client_id="a" * 32)   # 32 chars = valid_id regex
    # Replace the real requests.Session so no test hits the network.
    p._session = MagicMock()
    return p


# ─────────────────────────────────────────────────────────────────────────
# _valid_id
# ─────────────────────────────────────────────────────────────────────────

def test_valid_id_accepts_20plus_char_alphanumeric():
    assert SoundCloudProvider._valid_id("a" * 20)
    assert SoundCloudProvider._valid_id("abc-DEF_123" + "x" * 12)


def test_valid_id_rejects_short_strings():
    assert not SoundCloudProvider._valid_id("short")
    assert not SoundCloudProvider._valid_id("a" * 19)


def test_valid_id_rejects_empty_and_none():
    assert not SoundCloudProvider._valid_id("")
    assert not SoundCloudProvider._valid_id(None)


def test_valid_id_rejects_forbidden_characters():
    """Space or punctuation invalidates it — the SC id is a URL-safe token."""
    assert not SoundCloudProvider._valid_id("a" * 15 + " " + "b" * 10)
    assert not SoundCloudProvider._valid_id("a" * 20 + "!")


# ─────────────────────────────────────────────────────────────────────────
# _ensure_client_id — the scraping fallback
# ─────────────────────────────────────────────────────────────────────────

def test_ensure_client_id_short_circuits_when_already_valid(provider):
    """Valid id already set → no HTTP call."""
    provider._client_id = "a" * 32
    provider._session.get.reset_mock()
    assert provider._ensure_client_id() is True
    provider._session.get.assert_not_called()


def test_ensure_client_id_extracts_from_asset_bundle(provider):
    """Home page returns HTML with N asset URLs; we fetch each and
    look for ``client_id:"..."`` — the first match wins."""
    provider._client_id = ""    # force scraping

    home = MagicMock()
    home.text = (
        '<script src="https://a-v2.sndcdn.com/assets/aaa.js"></script>'
        '<script src="https://a-v2.sndcdn.com/assets/bbb.js"></script>'
    )
    home.raise_for_status = MagicMock()

    empty = MagicMock()
    empty.text = "no client here"
    empty.raise_for_status = MagicMock()

    match_js = MagicMock()
    match_js.text = 'window.SC={client_id:"' + ("k" * 32) + '",...};'
    match_js.raise_for_status = MagicMock()

    # First script empty, second has the client_id.
    provider._session.get.side_effect = [home, empty, match_js]
    assert provider._ensure_client_id() is True
    assert provider._client_id == "k" * 32


def test_ensure_client_id_bails_when_no_asset_urls_found(provider):
    """SoundCloud changed HTML structure → no asset URLs match the regex
    → we log a warning and return False without crashing."""
    provider._client_id = ""
    home = MagicMock()
    home.text = "<html>Zero matches for the asset URL regex</html>"
    home.raise_for_status = MagicMock()
    provider._session.get.return_value = home
    assert provider._ensure_client_id() is False


def test_ensure_client_id_bails_when_client_id_not_in_any_js(provider):
    """Assets found but none carry ``client_id:"..."``."""
    provider._client_id = ""
    home = MagicMock()
    home.text = '<script src="https://a-v2.sndcdn.com/assets/x.js"></script>'
    home.raise_for_status = MagicMock()
    js = MagicMock()
    js.text = 'window.SC = { some_other: "not the id" };'
    js.raise_for_status = MagicMock()
    provider._session.get.side_effect = [home, js]
    assert provider._ensure_client_id() is False


def test_ensure_client_id_handles_network_error(provider):
    """A network exception must NOT propagate — return False silently."""
    provider._client_id = ""
    provider._session.get.side_effect = Exception("network down")
    assert provider._ensure_client_id() is False


def test_ensure_client_id_caps_asset_walk_at_12(provider):
    """We only try the first 12 asset URLs — SoundCloud sometimes ships
    50+ bundles and we don't want to fetch them all."""
    provider._client_id = ""
    # 20 asset URLs; only the 13th+ have the client_id → we should FAIL.
    asset_urls = "\n".join(
        f'<script src="https://a-v2.sndcdn.com/assets/a{i}.js"></script>'
        for i in range(20)
    )
    home = MagicMock()
    home.text = asset_urls
    home.raise_for_status = MagicMock()

    responses = [home]
    for i in range(20):
        r = MagicMock()
        r.text = (f'client_id:"{"z" * 32}"' if i >= 15 else "nothing here")
        r.raise_for_status = MagicMock()
        responses.append(r)
    provider._session.get.side_effect = responses

    # Because the match is at index 15 (16th JS), and we cap at 12, we bail.
    assert provider._ensure_client_id() is False


# ─────────────────────────────────────────────────────────────────────────
# _api — client_id gating + query construction
# ─────────────────────────────────────────────────────────────────────────

def test_api_returns_none_when_client_id_cant_be_ensured(provider):
    """_ensure_client_id returning False must short-circuit the call."""
    with patch.object(provider, "_ensure_client_id", return_value=False):
        assert provider._api("/some/path") is None


def test_api_includes_client_id_in_query(provider):
    provider._client_id = "a" * 32
    resp = MagicMock()
    resp.raise_for_status = MagicMock()
    resp.json.return_value = {"ok": True}
    provider._session.get.return_value = resp

    provider._api("/search", {"q": "daft"})
    params = provider._session.get.call_args[1]["params"]
    assert params["client_id"] == "a" * 32
    assert params["q"] == "daft"


def test_api_returns_none_on_http_error(provider):
    provider._client_id = "a" * 32
    provider._session.get.side_effect = Exception("500")
    assert provider._api("/anything") is None


# ─────────────────────────────────────────────────────────────────────────
# _to_info — the mapping heart
# ─────────────────────────────────────────────────────────────────────────

def _sc_track(**overrides):
    """A minimally realistic SoundCloud API track dict."""
    base = {
        "id":            12345,
        "title":         "Cool Track",
        "user":          {"username": "ArtistName"},
        "duration":      210000,
        "genre":         "Electronic",
        "artwork_url":   "https://i1.sndcdn.com/artworks-x-large.jpg",
        "permalink_url": "https://soundcloud.com/artist/cool-track",
        "created_at":    "2024-03-15T10:00:00Z",
    }
    base.update(overrides)
    return base


def test_to_info_full_shape(provider):
    ti = provider._to_info(_sc_track())
    assert ti is not None
    assert ti.title       == "Cool Track"
    assert ti.artists     == ["ArtistName"]
    assert ti.duration_ms == 210000
    assert ti.genre       == "Electronic"
    assert ti.year        == "2024"
    assert ti.platform    == "soundcloud"
    assert ti.track_id    == "12345"


def test_to_info_upgrades_artwork_to_original(provider):
    """SoundCloud CDN serves the original upload at ``-original``.  We
    should upgrade the default ``-large`` suffix to get max resolution."""
    t = _sc_track(artwork_url="https://i1.sndcdn.com/artworks-abc-large.jpg")
    ti = provider._to_info(t)
    assert ti.cover_url == "https://i1.sndcdn.com/artworks-abc-original.jpg"


def test_to_info_splits_artist_dash_title_convention(provider):
    """SoundCloud users frequently title tracks ``Artist - Title``.
    Split it so history dedup works across platforms."""
    t = _sc_track(title="RealArtist - RealSong",
                  user={"username": "UploadedByProxy"})
    ti = provider._to_info(t)
    assert ti.artists == ["RealArtist"]
    assert ti.title   == "RealSong"


def test_to_info_keeps_uploader_when_no_dash(provider):
    t = _sc_track(title="Plain title", user={"username": "TheArtist"})
    ti = provider._to_info(t)
    assert ti.artists == ["TheArtist"]
    assert ti.title   == "Plain title"


def test_to_info_falls_back_to_unknown_user(provider):
    t = _sc_track(user={})
    ti = provider._to_info(t)
    assert ti.artists == ["Unknown"]


def test_to_info_prefers_release_date_over_created_at(provider):
    t = _sc_track(release_date="2020-01-01",
                   created_at="2024-05-05T00:00:00Z")
    ti = provider._to_info(t)
    assert ti.year == "2020"


def test_to_info_returns_none_on_empty_input(provider):
    assert provider._to_info(None) is None
    assert provider._to_info({}) is None


# ─────────────────────────────────────────────────────────────────────────
# search / search_albums
# ─────────────────────────────────────────────────────────────────────────

def test_search_maps_results(provider):
    with patch.object(provider, "_api", return_value={
        "collection": [_sc_track(id=1, title="A - S1"),
                       _sc_track(id=2, title="B - S2")],
    }):
        out = provider.search("query")
    assert len(out) == 2


def test_search_respects_limit(provider):
    """Even when SoundCloud returns more than N, we slice at limit."""
    with patch.object(provider, "_api", return_value={
        "collection": [_sc_track(id=i, title=f"a - t{i}") for i in range(10)],
    }):
        out = provider.search("query", limit=3)
    assert len(out) == 3


def test_search_returns_empty_on_none_response(provider):
    """API failure → [] (never propagate)."""
    with patch.object(provider, "_api", return_value=None):
        assert provider.search("anything") == []


def test_search_albums_maps_playlists(provider):
    with patch.object(provider, "_api", return_value={
        "collection": [{
            "id":            777,
            "title":         "My Set",
            "user":          {"username": "DJ"},
            "artwork_url":   "https://i.sndcdn.com/artworks-x-large.jpg",
            "permalink_url": "https://soundcloud.com/dj/my-set",
            "track_count":   12,
        }],
    }):
        out = provider.search_albums("dj set")
    assert len(out) == 1
    assert out[0].is_album is True
    assert out[0].track_count == 12


# ─────────────────────────────────────────────────────────────────────────
# get_track / get_tracks_from_url
# ─────────────────────────────────────────────────────────────────────────

def test_get_track_by_url_calls_resolve(provider):
    with patch.object(provider, "_api",
                      return_value=_sc_track(id=999)) as api:
        provider.get_track("https://soundcloud.com/artist/song")
    call = api.call_args[0]
    assert call[0] == "/resolve"
    assert call[1]["url"] == "https://soundcloud.com/artist/song"


def test_get_track_by_id_calls_tracks_endpoint(provider):
    with patch.object(provider, "_api",
                      return_value=_sc_track(id=999)) as api:
        provider.get_track("999")
    assert api.call_args[0][0] == "/tracks/999"


def test_get_track_none_when_api_returns_none(provider):
    with patch.object(provider, "_api", return_value=None):
        assert provider.get_track("999") is None


def test_get_tracks_from_url_single_track(provider):
    with patch.object(provider, "_api", return_value={
        "kind": "track", **_sc_track(id=1, title="a - S"),
    }):
        out = provider.get_tracks_from_url("https://soundcloud.com/x/y")
    assert len(out) == 1


def test_get_tracks_from_url_playlist_hydrates_missing_titles(provider):
    """SoundCloud playlists return a mix of full track objects and stubs
    (``{id: ..., ...}`` with no title).  We must batch-fetch the stubs
    via ``/tracks?ids=`` to get their real metadata."""
    hydrated_1 = _sc_track(id=1, title="a - S1")
    stub_2 = {"id": 2}   # title missing → needs hydration
    full_2 = _sc_track(id=2, title="a - S2")

    def _api_side(path, params=None):
        if path == "/resolve":
            return {"kind": "playlist", "tracks": [hydrated_1, stub_2]}
        if path == "/tracks":
            # Assert the batch fetch was called with the missing IDs.
            assert params["ids"] == "2"
            return [full_2]
        return None

    with patch.object(provider, "_api", side_effect=_api_side):
        out = provider.get_tracks_from_url("https://soundcloud.com/pl")
    assert len(out) == 2
    # Both titles are present (i.e. stub 2 was hydrated).
    titles = {t.title for t in out}
    assert titles == {"S1", "S2"}


def test_get_tracks_from_url_playlist_no_hydration_when_all_have_titles(provider):
    """If every track already has a title, no batch fetch needed."""
    calls = []

    def _api_side(path, params=None):
        calls.append(path)
        if path == "/resolve":
            return {
                "kind": "playlist",
                "tracks": [_sc_track(id=1, title="a - S1"),
                           _sc_track(id=2, title="a - S2")],
            }
        return None

    with patch.object(provider, "_api", side_effect=_api_side):
        out = provider.get_tracks_from_url("https://soundcloud.com/pl")
    assert len(out) == 2
    # Only /resolve should be called — no /tracks batch fetch.
    assert calls == ["/resolve"]


def test_get_tracks_from_url_user_returns_top_tracks(provider):
    """Artist URL → /users/{id}/tracks with a limit."""
    def _api_side(path, params=None):
        if path == "/resolve":
            return {"kind": "user", "id": 42}
        if path == "/users/42/tracks":
            assert params["limit"] == 50
            return {"collection": [_sc_track(id=1, title="a - S1"),
                                   _sc_track(id=2, title="a - S2")]}
        return None

    with patch.object(provider, "_api", side_effect=_api_side):
        out = provider.get_tracks_from_url("https://soundcloud.com/artist")
    assert len(out) == 2


def test_get_tracks_from_url_empty_on_unknown_kind(provider):
    """Wave / stream / etc. that we don't handle → clean empty."""
    with patch.object(provider, "_api",
                      return_value={"kind": "stream"}):
        out = provider.get_tracks_from_url("https://soundcloud.com/stream")
    assert out == []


def test_get_tracks_from_url_empty_on_resolve_failure(provider):
    with patch.object(provider, "_api", return_value=None):
        assert provider.get_tracks_from_url("https://soundcloud.com/x") == []


# ─────────────────────────────────────────────────────────────────────────
# name / available
# ─────────────────────────────────────────────────────────────────────────

def test_name_property(provider):
    assert provider.name == "SoundCloud"


def test_available_always_true():
    """SoundCloud has no hard credentials requirement — always available."""
    p = SoundCloudProvider()
    assert p.available is True
