"""
metadata/beatport.py
=====================
Beatport metadata client.

Beatport is the de-facto catalogue for electronic music: its BPM, key
(Camelot), genre, label and release info are curated and accurate.
This module uses Beatport ONLY as a metadata source — no audio is ever
downloaded from beatport.com (their catalogue is paid + DRM).

The public Next.js site embeds the search results as JSON inside a
``<script id="__NEXT_DATA__">`` tag.  We parse that tag rather than the
authenticated REST API so the client works without an account.

Returns dicts shaped like ``lookup_getsongbpm`` so the rest of the
pipeline doesn't care which source the metadata came from.
"""
from __future__ import annotations

import json
import logging
import os
import re
import threading
import time
from typing import Optional

log = logging.getLogger("dj_tracks.beatport")

# ── Disk cache ───────────────────────────────────────────────────────────────
# BPM, key and label of a released track don't change, so cache forever.
# Negative results (None) are cached too — with a short 7-day TTL — so we
# don't hammer Beatport every retry for tracks they don't have.

_CACHE_LOCK = threading.Lock()
_CACHE: Optional[dict] = None
_CACHE_PATH: Optional[str] = None
_NEG_TTL_SEC = 7 * 24 * 3600


def _cache_path() -> str:
    global _CACHE_PATH
    if _CACHE_PATH is not None:
        return _CACHE_PATH
    try:
        from platformdirs import user_cache_dir
        d = user_cache_dir("DJ Tracks", "DJ Tracks")
    except Exception:
        d = os.path.join(os.path.expanduser("~"), ".dj_tracks_cache")
    os.makedirs(d, exist_ok=True)
    _CACHE_PATH = os.path.join(d, "beatport.json")
    return _CACHE_PATH


def _load_cache() -> dict:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    try:
        with open(_cache_path(), "r", encoding="utf-8") as fh:
            _CACHE = json.load(fh) or {}
    except Exception:
        _CACHE = {}
    return _CACHE


def _save_cache() -> None:
    if _CACHE is None:
        return
    path = _cache_path()
    tmp  = path + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(_CACHE, fh, ensure_ascii=False)
        os.replace(tmp, path)
    except Exception as exc:
        log.debug(f"[Beatport] cache save failed: {exc}")


def _cache_key(artist: str, title: str) -> str:
    return f"{(artist or '').strip().lower()}|{(title or '').strip().lower()}"


def _cache_get(key: str) -> tuple[bool, Optional[dict]]:
    """Return (hit, value).  value is None for a cached negative."""
    with _CACHE_LOCK:
        entry = _load_cache().get(key)
    if entry is None:
        return False, None
    if entry.get("data") is None:
        # Negative cache — check TTL.
        if time.time() - entry.get("t", 0) > _NEG_TTL_SEC:
            return False, None
        return True, None
    return True, entry["data"]


def _cache_put(key: str, value: Optional[dict]) -> None:
    with _CACHE_LOCK:
        _load_cache()[key] = {"data": value, "t": int(time.time())}
        _save_cache()

_SEARCH_URL = "https://www.beatport.com/search/tracks?q={q}"
_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}

_NEXT_DATA_RE = re.compile(
    r'<script[^>]+id="__NEXT_DATA__"[^>]*>(.*?)</script>',
    re.DOTALL,
)

# Beatport publishes the Camelot wheel as (number, letter) — letter is
# "A" for minor, "B" for major.  Their own JSON already includes both.


def _http_get(url: str, session=None, timeout: float = 8.0) -> Optional[str]:
    try:
        import requests
        s = session if session is not None else requests
        r = s.get(url, headers=_HEADERS, timeout=timeout)
        if r.status_code == 200:
            return r.text
        log.debug(f"[Beatport] HTTP {r.status_code} for {url}")
    except Exception as exc:
        log.debug(f"[Beatport] request failed: {exc}")
    return None


def _extract_next_data(html: str) -> Optional[dict]:
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except Exception:
        return None


def _walk_for_tracks(node, out: list) -> None:
    """Beatport reshuffles the location of the track list between site
    versions, so we walk the whole __NEXT_DATA__ tree looking for any
    list of dicts that look like track records (have bpm + a track id)."""
    if isinstance(node, dict):
        if ("bpm" in node and ("track_id" in node or "guid" in node)
                and "artists" in node):
            out.append(node)
            return
        for v in node.values():
            _walk_for_tracks(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_for_tracks(v, out)


def _extract_tracks(data: dict) -> list:
    """Pull the track list from __NEXT_DATA__.  Tries the well-known
    React-Query location first, then walks the tree as a fallback."""
    out: list = []
    try:
        queries = data["props"]["pageProps"]["dehydratedState"]["queries"]
        for q in queries:
            qk = q.get("queryKey", [])
            if qk and isinstance(qk[0], str) and "search-tracks" in qk[0]:
                payload = q.get("state", {}).get("data", {})
                inner = payload.get("data") if isinstance(payload, dict) else None
                if isinstance(inner, list):
                    out.extend(inner)
    except Exception:
        pass
    if not out:
        _walk_for_tracks(data, out)
    return out


_KEY_CAMELOT: dict = {}
# Build a lookup that accepts both sharp and flat spellings for every
# pitch — Beatport mixes them ("Ab Minor", "A# Minor", "Bb Major"…).
_SHARP_TO_FLAT = {"C#": "Db", "D#": "Eb", "F#": "Gb",
                  "G#": "Ab", "A#": "Bb"}
_FLAT_TO_SHARP = {v: k for k, v in _SHARP_TO_FLAT.items()}

def _register_key(pitch: str, mode: str, camelot: str) -> None:
    """Register one (pitch, mode) → camelot mapping with every
    enharmonic spelling that could plausibly appear."""
    variants = {pitch}
    if pitch in _SHARP_TO_FLAT:
        variants.add(_SHARP_TO_FLAT[pitch])
    if pitch in _FLAT_TO_SHARP:
        variants.add(_FLAT_TO_SHARP[pitch])
    for p in variants:
        _KEY_CAMELOT[(p, mode)] = camelot

for _p, _m, _c in [
    ("C", "maj", "8B"),  ("A", "min", "8A"),
    ("G", "maj", "9B"),  ("E", "min", "9A"),
    ("D", "maj", "10B"), ("B", "min", "10A"),
    ("A", "maj", "11B"), ("F#", "min", "11A"),
    ("E", "maj", "12B"), ("C#", "min", "12A"),
    ("B", "maj", "1B"),  ("G#", "min", "1A"),  # G#m == Abm
    ("F#", "maj", "2B"), ("D#", "min", "2A"),  # D#m == Ebm
    ("Db", "maj", "3B"), ("Bb", "min", "3A"),  # Bbm == A#m
    ("Ab", "maj", "4B"), ("F", "min", "4A"),
    ("Eb", "maj", "5B"), ("C", "min", "5A"),
    ("Bb", "maj", "6B"), ("G", "min", "6A"),
    ("F", "maj", "7B"),  ("D", "min", "7A"),
]:
    _register_key(_p, _m, _c)


def _camelot_from_key_name(key_name: str) -> str:
    """'A min' / 'F♯ maj' / 'Bb Minor' → '8A' / '2B' / '3A'."""
    if not key_name:
        return ""
    s = (key_name.replace("♯", "#")
                 .replace("♭", "b")
                 .strip())
    parts = s.split()
    if len(parts) < 2:
        return ""
    pitch = parts[0]
    mode  = "maj" if parts[1].lower().startswith("maj") else "min"
    return _KEY_CAMELOT.get((pitch, mode), "")


def _normalise(track: dict) -> dict:
    """Reshape a raw Beatport track dict into the lookup_getsongbpm
    schema used by the rest of the pipeline."""
    bpm  = track.get("bpm") or None
    # Beatport calls it track_name on the search endpoint.
    name = (track.get("track_name") or track.get("name") or "").strip()
    mix  = (track.get("mix_name") or "").strip()

    # Key — the search endpoint only gives key_name (e.g. "A min"); the
    # track detail endpoint also includes a precomputed camelot but we
    # don't need to round-trip there for that.
    key = (track.get("key_name") or "").strip()
    camelot = _camelot_from_key_name(key)

    # Genre is a list of {genre_id, genre_name}.
    genre = ""
    g = track.get("genre")
    if isinstance(g, list) and g:
        first = g[0]
        if isinstance(first, dict):
            genre = (first.get("genre_name") or "").strip()
    elif isinstance(g, dict):
        genre = (g.get("genre_name") or g.get("name") or "").strip()
    elif isinstance(g, str):
        genre = g.strip()

    # Label — exposed as a top-level dict on the search endpoint.
    label = ""
    lab = track.get("label")
    if isinstance(lab, dict):
        label = (lab.get("label_name") or lab.get("name") or "").strip()
    elif isinstance(lab, str):
        label = lab.strip()

    # Release year — "publish_date" is "YYYY-MM-DD".
    year = ""
    pub = (track.get("publish_date") or track.get("release_date") or "")
    if pub and len(pub) >= 4 and pub[:4].isdigit():
        year = pub[:4]

    # Artists / remixers — Beatport returns a single artists list with
    # "artist_type_name" telling us which is which.
    artists, remixers = [], []
    for a in (track.get("artists") or []):
        if not isinstance(a, dict):
            continue
        nm = (a.get("artist_name") or a.get("name") or "").strip()
        if not nm:
            continue
        if (a.get("artist_type_name") or "").lower() == "remixer":
            remixers.append(nm)
        else:
            artists.append(nm)
    # Older / alternate shape exposed a separate remixers field.
    for a in (track.get("remixers") or []):
        if isinstance(a, dict):
            nm = (a.get("artist_name") or a.get("name") or "").strip()
            if nm and nm not in remixers:
                remixers.append(nm)

    isrc = (track.get("isrc") or "").strip()

    return {
        "title":      name,
        "mix":        mix,
        "artists":    artists,
        "remixers":   remixers,
        "bpm":        int(bpm) if isinstance(bpm, (int, float)) else None,
        "key":        key,
        "camelot":    camelot,
        "genre":      genre,
        "publisher":  label,
        "year":       year,
        "isrc":       isrc,
        "source":     "beatport",
    }


def _score(query_artist: str, query_title: str, track: dict) -> float:
    """Fuzzy score 0-100 of how well *track* matches the query.

    Prefers exact substring matches on artist + title, then falls back
    to rapidfuzz's WRatio.  Penalises when neither artist matches.
    """
    qa = (query_artist or "").lower().strip()
    qt = (query_title  or "").lower().strip()
    artists = [a.lower() for a in track["artists"] + track["remixers"]]
    name    = track["title"].lower()
    mix     = track["mix"].lower()
    full    = (name + " " + mix).strip()

    # Hard floor: at least one artist token must overlap.
    if qa and artists:
        if not any(qa in a or a in qa for a in artists):
            try:
                from rapidfuzz import fuzz
                if max(fuzz.partial_ratio(qa, a) for a in artists) < 70:
                    return 0.0
            except Exception:
                return 0.0

    try:
        from rapidfuzz import fuzz
        s_title = max(fuzz.WRatio(qt, name), fuzz.WRatio(qt, full))
        s_art   = (max(fuzz.WRatio(qa, a) for a in artists)
                   if qa and artists else 60.0)
        return 0.65 * s_title + 0.35 * s_art
    except Exception:
        # rapidfuzz missing — degrade to substring scoring.
        score = 0.0
        if qt and qt in full:
            score += 60.0
        if qa and any(qa in a for a in artists):
            score += 40.0
        return score


def search(query_artist: str, query_title: str, session=None,
           max_results: int = 5) -> list[dict]:
    """Return up to *max_results* Beatport tracks scored against the
    query, best first.  Empty list when nothing is found or the network
    request fails."""
    qa = (query_artist or "").strip()
    qt = (query_title  or "").strip()
    if not (qa or qt):
        return []
    import urllib.parse
    q = urllib.parse.quote_plus(f"{qa} {qt}".strip())
    html = _http_get(_SEARCH_URL.format(q=q), session=session)
    if not html:
        return []
    data = _extract_next_data(html)
    if not data:
        return []
    raw = _extract_tracks(data)
    if not raw:
        return []
    # Dedup by (name, first artist) — Beatport often lists the same
    # track multiple times across releases.
    seen: set = set()
    tracks: list[dict] = []
    for t in raw:
        norm = _normalise(t)
        key = (norm["title"].lower(),
               (norm["artists"][0].lower() if norm["artists"] else ""))
        if key in seen:
            continue
        seen.add(key)
        norm["_score"] = _score(qa, qt, norm)
        tracks.append(norm)
    tracks.sort(key=lambda t: t["_score"], reverse=True)
    return tracks[:max_results]


def lookup_beatport(artist: str, title: str,
                    session=None,
                    min_score: float = 70.0,
                    use_cache: bool = True) -> Optional[dict]:
    """Return the best Beatport match if it scores above *min_score*,
    else None.  Output shape mirrors lookup_getsongbpm so callers can
    treat both sources interchangeably.

    Results (positive and negative) are cached to disk so the second
    enrichment of the same track is free.  Pass ``use_cache=False`` to
    force a fresh lookup.
    """
    key = _cache_key(artist, title)
    if use_cache:
        hit, value = _cache_get(key)
        if hit:
            return value

    results = search(artist, title, session=session, max_results=5)
    if not results:
        if use_cache:
            _cache_put(key, None)
        return None
    best = results[0]
    if best.get("_score", 0) < min_score:
        log.debug(f"[Beatport] best match below threshold: "
                  f"{best['title']} ({best.get('_score', 0):.1f})")
        if use_cache:
            _cache_put(key, None)
        return None
    out = {k: v for k, v in best.items() if k != "_score"}
    # Drop empty / null fields so the caller can use `dict.update()`
    # without overwriting good data with nothing.
    cleaned = {k: v for k, v in out.items() if v not in (None, "", [], 0)}
    if use_cache:
        _cache_put(key, cleaned)
    return cleaned
