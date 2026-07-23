"""Tests for ``metadata.beatport`` — the DJ metadata source.

Beatport is the de-facto catalogue for electronic music: real BPM,
Camelot-notation key, curated genre/label.  A regression here means
tracks come out without any of that so DJs can't harmonic-mix them.

Tests mock every HTTP call and isolate the module-level disk cache
per test so nothing hits the real Beatport site or the user's
``beatport.json`` cache file.

Focus:
- ``_cache_key`` — normalisation for artist|title keys
- ``_cache_get`` / ``_cache_put`` — hit/miss + negative TTL
- ``_camelot_from_key_name`` — the sharp/flat enharmonic table
- ``_normalise`` — Beatport track dict → schema dict
- ``_score`` — fuzzy match + hard artist floor
- ``_extract_next_data`` / ``_walk_for_tracks`` / ``_extract_tracks``
- ``search`` — end-to-end orchestration
- ``lookup_beatport`` — cache + threshold + result cleanup
"""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

import pytest

from metadata import beatport
from metadata.beatport import (
    _cache_get,
    _cache_key,
    _cache_put,
    _camelot_from_key_name,
    _extract_next_data,
    _extract_tracks,
    _normalise,
    _score,
    _walk_for_tracks,
    lookup_beatport,
    search,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixture — isolate the disk cache per test
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _isolate_cache(tmp_path, monkeypatch):
    """Redirect the module-level cache to a temp file AND reset the
    in-memory cache dict so tests don't leak into each other."""
    cache_file = tmp_path / "beatport.json"
    monkeypatch.setattr(beatport, "_CACHE_PATH", str(cache_file))
    monkeypatch.setattr(beatport, "_CACHE", None)   # force reload from empty
    yield


# ─────────────────────────────────────────────────────────────────────────
# _cache_key
# ─────────────────────────────────────────────────────────────────────────

def test_cache_key_lowercases_and_trims():
    assert _cache_key("  Daft Punk  ", " Get Lucky ") == "daft punk|get lucky"


def test_cache_key_handles_empty_inputs():
    assert _cache_key("", "") == "|"


def test_cache_key_stable_across_case_variants():
    """Different casings must produce the same key — otherwise cache misses
    every time the caller passes a differently-cased query."""
    assert _cache_key("BEYONCE", "HALO") == _cache_key("beyonce", "halo")


# ─────────────────────────────────────────────────────────────────────────
# _cache_get / _cache_put
# ─────────────────────────────────────────────────────────────────────────

def test_cache_miss_returns_no_hit():
    hit, value = _cache_get("unknown-key")
    assert (hit, value) == (False, None)


def test_cache_positive_roundtrip():
    """Put a real payload, get it back on the next lookup."""
    _cache_put("k1", {"bpm": 128, "camelot": "8A"})
    hit, value = _cache_get("k1")
    assert hit is True
    assert value == {"bpm": 128, "camelot": "8A"}


def test_cache_negative_within_ttl_is_hit():
    """A cached None (Beatport didn't find the track) counts as a hit
    within the negative TTL — we skip the network request."""
    _cache_put("k-neg", None)
    hit, value = _cache_get("k-neg")
    assert hit is True
    assert value is None


def test_cache_negative_expires_after_ttl():
    """After NEG_TTL_SEC (7 days), a negative-cached entry is refetched."""
    _cache_put("k-old", None)
    # Rewind the timestamp past the TTL.
    old_time = time.time() - (beatport._NEG_TTL_SEC + 3600)
    beatport._CACHE["k-old"]["t"] = old_time
    hit, value = _cache_get("k-old")
    assert (hit, value) == (False, None)


def test_cache_positive_never_expires():
    """Positive entries (real Beatport metadata) live forever — BPM/key
    of a released track don't change."""
    _cache_put("k-pos", {"bpm": 128})
    beatport._CACHE["k-pos"]["t"] = 0   # far in the past
    hit, value = _cache_get("k-pos")
    assert hit is True
    assert value == {"bpm": 128}


def test_cache_survives_reload_from_disk(tmp_path):
    """Writing to _CACHE also flushes to disk — a fresh load reads it back."""
    _cache_put("persist-me", {"bpm": 140})
    beatport._CACHE = None
    hit, value = _cache_get("persist-me")
    assert (hit, value) == (True, {"bpm": 140})


# ─────────────────────────────────────────────────────────────────────────
# _camelot_from_key_name
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("key_name,expected", [
    ("A min",       "8A"),
    ("A Minor",     "8A"),
    ("A minor",     "8A"),
    ("C maj",       "8B"),
    ("C Major",     "8B"),
    # Sharps
    ("F# maj",      "2B"),
    ("F# min",      "11A"),
    # Flats (enharmonic to sharps above)
    ("Gb maj",      "2B"),      # Gb = F#
    ("Ab min",      "1A"),      # Abm = G#m
    # Unicode ♯ / ♭
    ("F♯ maj",      "2B"),
    ("A♭ maj",      "4B"),      # Ab maj
])
def test_camelot_from_key_name(key_name, expected):
    assert _camelot_from_key_name(key_name) == expected


def test_camelot_empty_string_returns_empty():
    assert _camelot_from_key_name("") == ""


def test_camelot_malformed_returns_empty():
    """Missing mode → empty (need both pitch and mode to disambiguate)."""
    assert _camelot_from_key_name("A") == ""


def test_camelot_unknown_pitch_returns_empty():
    """Pitch that isn't in the table (e.g. 'H') returns empty."""
    assert _camelot_from_key_name("H maj") == ""


# ─────────────────────────────────────────────────────────────────────────
# _normalise — Beatport dict → schema dict
# ─────────────────────────────────────────────────────────────────────────

def _bp_track(**overrides):
    """A minimally realistic Beatport __NEXT_DATA__ track object."""
    base = {
        "track_id":     123,
        "track_name":   "Get Lucky",
        "mix_name":     "Original Mix",
        "bpm":          116,
        "key_name":     "F# min",
        "publish_date": "2013-05-17",
        "isrc":         "USQX91300224",
        "artists": [
            {"artist_name": "Daft Punk", "artist_type_name": "Artist"},
        ],
        "genre":  [{"genre_id": 1, "genre_name": "Nu Disco"}],
        "label":  {"label_id": 1, "label_name": "Columbia"},
    }
    base.update(overrides)
    return base


def test_normalise_full_shape():
    n = _normalise(_bp_track())
    assert n["title"]     == "Get Lucky"
    assert n["mix"]       == "Original Mix"
    assert n["bpm"]       == 116
    assert n["key"]       == "F# min"
    assert n["camelot"]   == "11A"
    assert n["genre"]     == "Nu Disco"
    assert n["publisher"] == "Columbia"
    assert n["year"]      == "2013"
    assert n["artists"]   == ["Daft Punk"]
    assert n["remixers"]  == []
    assert n["isrc"]      == "USQX91300224"
    assert n["source"]    == "beatport"


def test_normalise_splits_artists_and_remixers():
    """artist_type_name='Remixer' → remixers list; anything else → artists."""
    n = _normalise(_bp_track(artists=[
        {"artist_name": "Original", "artist_type_name": "Artist"},
        {"artist_name": "The DJ",   "artist_type_name": "Remixer"},
        {"artist_name": "Producer", "artist_type_name": "Producer"},
    ]))
    assert n["artists"]  == ["Original", "Producer"]
    assert n["remixers"] == ["The DJ"]


def test_normalise_dedups_remixers_from_alt_field():
    """Some responses expose remixers in both the artists list AND a
    separate 'remixers' field.  The second source must not duplicate."""
    n = _normalise(_bp_track(
        artists=[
            {"artist_name": "The DJ", "artist_type_name": "Remixer"},
        ],
        remixers=[{"artist_name": "The DJ"}],
    ))
    assert n["remixers"] == ["The DJ"]


def test_normalise_handles_string_genre():
    """Older Beatport payloads embedded genre as a plain string."""
    n = _normalise(_bp_track(genre="Techno"))
    assert n["genre"] == "Techno"


def test_normalise_handles_dict_genre():
    n = _normalise(_bp_track(genre={"genre_name": "House"}))
    assert n["genre"] == "House"


def test_normalise_handles_string_label():
    n = _normalise(_bp_track(label="Independent"))
    assert n["publisher"] == "Independent"


def test_normalise_falls_back_to_release_date_for_year():
    n = _normalise(_bp_track(publish_date="", release_date="2020-01-01"))
    assert n["year"] == "2020"


def test_normalise_bpm_none_when_missing():
    n = _normalise(_bp_track(bpm=None))
    assert n["bpm"] is None


def test_normalise_falls_back_to_name_when_no_track_name():
    """Some detail endpoints use 'name' instead of 'track_name'."""
    n = _normalise({"name": "Xyz", "artists": [], "genre": [], "label": {},
                     "bpm": 128})
    assert n["title"] == "Xyz"


# ─────────────────────────────────────────────────────────────────────────
# _score — fuzzy match
# ─────────────────────────────────────────────────────────────────────────

def test_score_high_on_exact_match():
    track = _normalise(_bp_track())
    assert _score("Daft Punk", "Get Lucky", track) > 90


def test_score_zero_when_artist_completely_different():
    """Hard floor: no artist overlap AND fuzzy < 70 → 0.0."""
    track = _normalise(_bp_track())
    assert _score("Nickelback", "Photograph", track) == 0.0


def test_score_ignores_missing_query_artist():
    """When the caller didn't provide a query artist, drop the artist
    check and score on title only."""
    track = _normalise(_bp_track())
    assert _score("", "Get Lucky", track) > 40


# ─────────────────────────────────────────────────────────────────────────
# _extract_next_data + _walk_for_tracks
# ─────────────────────────────────────────────────────────────────────────

def test_extract_next_data_returns_parsed_json():
    html = ('<html><script id="__NEXT_DATA__" type="application/json">'
            '{"foo": "bar"}</script></html>')
    assert _extract_next_data(html) == {"foo": "bar"}


def test_extract_next_data_none_when_tag_missing():
    assert _extract_next_data("<html>no script</html>") is None


def test_extract_next_data_none_when_json_malformed():
    html = '<script id="__NEXT_DATA__">{not-json}</script>'
    assert _extract_next_data(html) is None


def test_walk_for_tracks_finds_track_shaped_nodes():
    """Any dict with bpm + (track_id or guid) + artists is a track."""
    data = {"props": {"pageProps": {"deep": {"tracks": [
        {"bpm": 128, "track_id": 1, "artists": [{"artist_name": "A"}]},
        {"bpm": 120, "guid":     "abc", "artists": []},
    ]}}}}
    out: list = []
    _walk_for_tracks(data, out)
    assert len(out) == 2


def test_walk_for_tracks_skips_non_track_dicts():
    """A dict without artists (or without an id) is not a track."""
    data = {"nope": {"bpm": 100, "no_artists": "no"}}
    out: list = []
    _walk_for_tracks(data, out)
    assert out == []


def test_extract_tracks_prefers_react_query_path():
    """The well-known React-Query location is faster than the tree walk;
    if it matches we use it and skip the walker."""
    data = {
        "props": {"pageProps": {"dehydratedState": {"queries": [
            {"queryKey":  ["search-tracks/query"],
             "state":     {"data": {"data": [
                 {"bpm": 128, "track_id": 1, "artists": []},
                 {"bpm": 120, "track_id": 2, "artists": []},
             ]}}}
        ]}}}
    }
    out = _extract_tracks(data)
    assert len(out) == 2


def test_extract_tracks_falls_back_to_walker_when_known_path_missing():
    """A layout change would break the known path — the walker rescues it."""
    data = {"random": {"nested": {"list": [
        {"bpm": 128, "track_id": 1, "artists": [{"artist_name": "A"}]}
    ]}}}
    out = _extract_tracks(data)
    assert len(out) == 1


# ─────────────────────────────────────────────────────────────────────────
# search — end-to-end orchestration
# ─────────────────────────────────────────────────────────────────────────

def _mock_next_data_html(tracks: list) -> str:
    """Build a fake Beatport search-result HTML page containing tracks."""
    payload = {"props": {"pageProps": {"dehydratedState": {"queries": [
        {"queryKey":  ["search-tracks"],
         "state":     {"data": {"data": tracks}}}
    ]}}}}
    return (f'<script id="__NEXT_DATA__" type="application/json">'
            f'{json.dumps(payload)}</script>')


def test_search_returns_empty_on_empty_query():
    assert search("", "") == []


def test_search_returns_empty_on_http_failure():
    with patch("metadata.beatport._http_get", return_value=None):
        assert search("Daft Punk", "Get Lucky") == []


def test_search_returns_empty_when_no_next_data():
    with patch("metadata.beatport._http_get",
               return_value="<html>no data</html>"):
        assert search("Daft Punk", "Get Lucky") == []


def test_search_returns_scored_and_sorted_results():
    """Best-matching track ranks first."""
    with patch("metadata.beatport._http_get",
               return_value=_mock_next_data_html([
                   _bp_track(track_id=1, track_name="Get Lucky",
                             artists=[{"artist_name": "Daft Punk"}]),
                   _bp_track(track_id=2, track_name="Random Song",
                             artists=[{"artist_name": "Unknown"}]),
               ])):
        results = search("Daft Punk", "Get Lucky")
    assert results[0]["title"] == "Get Lucky"


def test_search_dedups_same_track_different_releases():
    """Beatport often lists the same (title, artist) multiple times
    across releases — we keep only one."""
    with patch("metadata.beatport._http_get",
               return_value=_mock_next_data_html([
                   _bp_track(track_id=1, track_name="Same"),
                   _bp_track(track_id=2, track_name="Same"),
                   _bp_track(track_id=3, track_name="Same"),
               ])):
        results = search("Daft Punk", "Same")
    assert len(results) == 1


def test_search_respects_max_results():
    tracks = [_bp_track(track_id=i, track_name=f"Track {i}")
              for i in range(10)]
    with patch("metadata.beatport._http_get",
               return_value=_mock_next_data_html(tracks)):
        results = search("Daft Punk", "Track", max_results=3)
    assert len(results) == 3


# ─────────────────────────────────────────────────────────────────────────
# lookup_beatport — cache + threshold + cleanup
# ─────────────────────────────────────────────────────────────────────────

def test_lookup_returns_cached_positive_without_network():
    """Cached positive → no HTTP call at all."""
    _cache_put(_cache_key("A", "B"), {"bpm": 128, "camelot": "8A"})
    with patch("metadata.beatport.search") as srch:
        result = lookup_beatport("A", "B")
    assert result == {"bpm": 128, "camelot": "8A"}
    srch.assert_not_called()


def test_lookup_returns_none_from_cached_negative():
    """Cached None (recent Beatport miss) → skip the network call."""
    _cache_put(_cache_key("A", "B"), None)
    with patch("metadata.beatport.search") as srch:
        result = lookup_beatport("A", "B")
    assert result is None
    srch.assert_not_called()


def test_lookup_caches_negative_when_search_returns_empty():
    """A fresh negative should be cached so we don't retry every time."""
    with patch("metadata.beatport.search", return_value=[]):
        assert lookup_beatport("Nobody", "Nothing") is None
    hit, value = _cache_get(_cache_key("Nobody", "Nothing"))
    assert hit is True
    assert value is None


def test_lookup_returns_none_when_best_below_threshold():
    """min_score gate: even a match must clear the fuzzy threshold."""
    bad_match = {**_normalise(_bp_track(track_name="Wrong")),
                 "_score": 30.0}   # far below default min_score=70
    with patch("metadata.beatport.search", return_value=[bad_match]):
        assert lookup_beatport("A", "B") is None


def test_lookup_returns_cleaned_dict_on_hit():
    """Empty fields are dropped so callers can dict.update() safely."""
    good_match = {**_normalise(_bp_track()), "_score": 95.0}
    with patch("metadata.beatport.search", return_value=[good_match]):
        result = lookup_beatport("Daft Punk", "Get Lucky")
    assert "_score" not in result   # internal field
    # Non-empty fields survive.
    assert result["bpm"]     == 116
    assert result["camelot"] == "11A"
    # No empty fields.
    assert "" not in result.values()


def test_lookup_use_cache_false_skips_cache_read():
    """When use_cache=False, we must call search() even when a cached
    entry exists."""
    _cache_put(_cache_key("A", "B"), {"bpm": 999})
    good = {**_normalise(_bp_track()), "_score": 95.0}
    with patch("metadata.beatport.search", return_value=[good]) as srch:
        result = lookup_beatport("A", "B", use_cache=False)
    srch.assert_called_once()
    assert result["bpm"] == 116   # from search, not cache
