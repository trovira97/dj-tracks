"""
providers/bandcamp_provider.py
===============================
Bandcamp metadata + URL-resolution provider.

Bandcamp is one of the few legitimate, open music platforms that:

- Hosts a vast catalogue of independent/electronic/DJ-oriented music.
- Lets artists set tracks as free or paid; many are free-to-download.
- Exposes a public JSON search endpoint (no API key, no auth).
- Is fully supported by yt-dlp for the actual audio download.

This provider hits Bandcamp's `bcsearch_public_api` for search +
autocomplete results, and returns ``TrackInfo`` objects whose
``source_url`` points to the canonical track page so the downloader
can hand it directly to yt-dlp (no YouTube fallback needed).
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

import requests

from providers import MusicProvider, TrackInfo
from utils.logger import log


class BandcampProvider(MusicProvider):
    """
    Bandcamp provider using the public ``bcsearch_public_api`` endpoint.

    No credentials required.  Search results are filtered to tracks only
    (``search_filter="t"``); albums and artists are resolved on demand by
    :meth:`get_tracks_from_url`.
    """

    SEARCH_URL = "https://bandcamp.com/api/bcsearch_public_api/1/autocomplete_elastic"

    # Matches *.bandcamp.com URLs to detect track vs album vs artist pages.
    _TRACK_RE = re.compile(r"bandcamp\.com/track/", re.I)
    _ALBUM_RE = re.compile(r"bandcamp\.com/album/", re.I)

    def __init__(self) -> None:
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
            ),
            "Accept": "application/json",
            "Content-Type": "application/json",
            "Origin": "https://bandcamp.com",
            "Referer": "https://bandcamp.com/",
        })
        self._available = True
        log.info("[Bandcamp] Cliente iniciado (API pública)")

    @property
    def name(self) -> str:
        return "Bandcamp"

    @property
    def available(self) -> bool:
        return self._available

    # ── Conversion ────────────────────────────────────────────────────────────

    def _result_to_info(self, r: dict) -> Optional[TrackInfo]:
        """Convert one Bandcamp search-result item to :class:`TrackInfo`."""
        if not isinstance(r, dict):
            return None
        try:
            # img can be an int (image ID) or a full URL depending on endpoint
            # version; normalise to a full URL.  Suffix _0 returns the original
            # uploaded artwork (typically 1500×1500) instead of _10 (350×350).
            img = r.get("img") or ""
            if isinstance(img, int):
                img = f"https://f4.bcbits.com/img/a{img}_0.jpg"
            elif img and not img.startswith("http"):
                img = f"https://f4.bcbits.com{img}"
            else:
                # Already a URL — bump common downscale suffixes to _0.
                img = re.sub(r"_(2|3|4|5|6|7|8|9|10|11|13|16|17|20)\.(jpg|png)$",
                             r"_0.\2", img)

            title  = (r.get("name") or "").strip() or "Unknown"
            artist = (r.get("band_name") or "").strip() or "Unknown"
            url    = r.get("item_url_path") or r.get("url") or ""
            if url and not url.startswith("http"):
                url = f"https:{url}" if url.startswith("//") else f"https://{url}"

            return TrackInfo(
                title       = title,
                artists     = [artist],
                album       = (r.get("album_name") or "").strip(),
                cover_url   = img,
                source_url  = url,
                platform    = "bandcamp",
                track_id    = str(r.get("id") or ""),
            )
        except Exception as exc:
            log.warning(f"[Bandcamp] No se pudo convertir resultado: {exc}")
            return None

    # ── MusicProvider ─────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> List[TrackInfo]:
        if not query.strip():
            return []
        payload = {
            "search_text":   query,
            "search_filter": "t",       # tracks only
            "full_page":     True,
            "fan_id":        None,
        }
        try:
            resp = self._session.post(self.SEARCH_URL, json=payload, timeout=12)
            resp.raise_for_status()
            data = resp.json() or {}
        except Exception as exc:
            log.error(f"[Bandcamp] Error en búsqueda: {exc}")
            return []

        # Response shape: {"auto": {"results": [...]}}
        results = (data.get("auto") or {}).get("results") or []
        tracks: List[TrackInfo] = []
        for r in results[:limit]:
            # Only keep track items; the API can leak through albums / bands
            # depending on its mood.
            if r.get("type") and r.get("type") != "t":
                continue
            info = self._result_to_info(r)
            if info:
                tracks.append(info)
        return tracks

    def get_track(self, url_or_id: str) -> Optional[TrackInfo]:
        """Bandcamp identifiers are URLs; trying to ``GET`` a bare ID isn't useful."""
        if not url_or_id.startswith("http"):
            return None
        # Cheap implementation: build a TrackInfo from the URL alone — yt-dlp
        # will populate full metadata at download time.
        return TrackInfo(
            title      = url_or_id.rsplit("/", 1)[-1].replace("-", " ").title(),
            artists    = ["Unknown"],
            source_url = url_or_id,
            platform   = "bandcamp",
        )

    def get_tracks_from_url(self, url: str) -> List[TrackInfo]:
        """
        Resolve a Bandcamp URL.

        - Single track URL  → list of one :class:`TrackInfo`.
        - Album URL         → returned as a single placeholder TrackInfo so the
                              downloader can let yt-dlp expand it (Bandcamp
                              albums on yt-dlp produce one file per track
                              automatically when noplaylist=False).
        - Anything else     → empty list.
        """
        if self._TRACK_RE.search(url):
            return [TrackInfo(
                title      = url.rstrip("/").rsplit("/", 1)[-1].replace("-", " ").title(),
                artists    = ["Unknown"],
                source_url = url,
                platform   = "bandcamp",
            )]
        if self._ALBUM_RE.search(url):
            return [TrackInfo(
                title      = "Álbum de Bandcamp",
                artists    = ["Bandcamp"],
                source_url = url,
                platform   = "bandcamp",
            )]
        return []
