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
        from providers import BROWSER_USER_AGENT
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent":   BROWSER_USER_AGENT,
            "Accept":       "application/json",
            "Content-Type": "application/json",
            "Origin":       "https://bandcamp.com",
            "Referer":      "https://bandcamp.com/",
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

    def _result_to_info(self, r: dict) -> TrackInfo | None:
        """Convert one Bandcamp search-result item to :class:`TrackInfo`."""
        if not isinstance(r, dict):
            return None
        try:
            # img can be an int (image ID) or a full URL depending on endpoint
            # version; normalise to a full URL.  Suffix _10 = 1200×1200 — high
            # quality AND reliably served (the _0 "original" often 404s on the
            # public CDN, especially for search-result thumbnails).
            img = r.get("img") or ""
            if isinstance(img, int):
                img = f"https://f4.bcbits.com/img/a{img}_10.jpg"
            elif img and not img.startswith("http"):
                img = f"https://f4.bcbits.com{img}"
            else:
                # Already a URL — bump common small downscale suffixes to _10.
                img = re.sub(r"_(2|3|4|5|6|7|8|9|16|17|20)\.(jpg|png)$",
                             r"_10.\2", img)

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

    def search(self, query: str, limit: int = 10) -> list[TrackInfo]:
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
            # Bandcamp added bot protection in mid-2026: the public search
            # endpoint now returns an HTML challenge page instead of JSON
            # when hit from a non-browser client.  Detect that upfront and
            # bail cleanly — no results, no error spam in the logs.
            ctype = resp.headers.get("content-type", "")
            if "application/json" not in ctype:
                if self._available:
                    log.warning(
                        "[Bandcamp] endpoint devolvió HTML (probable bot-"
                        "protection Cloudflare) — desactivo Bandcamp para "
                        "esta sesión hasta que arreglemos el bypass"
                    )
                self._available = False
                return []
            data = resp.json() or {}
        except Exception as exc:
            log.warning(f"[Bandcamp] búsqueda no disponible: {exc}")
            self._available = False
            return []

        # Response shape: {"auto": {"results": [...]}}
        results = (data.get("auto") or {}).get("results") or []
        tracks: list[TrackInfo] = []
        for r in results[:limit]:
            # Only keep track items; the API can leak through albums / bands
            # depending on its mood.
            if r.get("type") and r.get("type") != "t":
                continue
            info = self._result_to_info(r)
            if info:
                tracks.append(info)
        return tracks

    def search_albums(self, query: str, limit: int = 10) -> list[TrackInfo]:
        """Search Bandcamp albums (search_filter='a').  The album URL resolves
        to all its tracks via :meth:`get_tracks_from_url`."""
        if not self._available:
            return []
        payload = {"search_text": query, "search_filter": "a",
                   "full_page": True, "fan_id": None}
        try:
            resp = self._session.post(self.SEARCH_URL, json=payload, timeout=12)
            resp.raise_for_status()
            if "application/json" not in resp.headers.get("content-type", ""):
                self._available = False
                return []
            data = resp.json() or {}
        except Exception as exc:
            log.warning(f"[Bandcamp] álbumes no disponible: {exc}")
            self._available = False
            return []
        results = (data.get("auto") or {}).get("results") or []
        out: list[TrackInfo] = []
        for r in results[:limit]:
            if r.get("type") and r.get("type") != "a":
                continue
            info = self._result_to_info(r)
            if info:
                info.is_album = True
                info.album    = info.title
                out.append(info)
        return out

    def get_track(self, url_or_id: str) -> TrackInfo | None:
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

    def get_tracks_from_url(self, url: str) -> list[TrackInfo]:
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
