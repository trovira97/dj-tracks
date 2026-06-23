"""
providers/applemusic_provider.py
Proveedor Apple Music — búsqueda y metadatos via iTunes Search API (pública).
"""
from __future__ import annotations

import re

import requests

from providers import MusicProvider, TrackInfo
from utils.logger import log


class AppleMusicProvider(MusicProvider):
    """
    Proveedor de metadatos usando la iTunes Search API (gratuita, sin auth).
    Para búsqueda avanzada con MusicKit se necesita una Apple Developer Key.
    """

    ITUNES_SEARCH = "https://itunes.apple.com/search"
    ITUNES_LOOKUP = "https://itunes.apple.com/lookup"

    def __init__(self, api_key: str = "") -> None:
        self._api_key = api_key  # Reservado para MusicKit v3
        self._session = requests.Session()
        self._session.headers["User-Agent"] = "Dj_Tracks_DW_crack/1.0"
        log.info("[AppleMusic] Proveedor iTunes iniciado (API pública)")

    @property
    def name(self) -> str:
        return "Apple Music"

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _item_to_info(self, item: dict) -> TrackInfo:
        # iTunes returns artwork at 100x100; the URL pattern lets us request any
        # resolution by string substitution.  3000x3000bb is the highest the
        # CDN reliably serves (the trailing "bb" gives white-background fill).
        artwork_100 = item.get("artworkUrl100", "")
        artwork     = artwork_100.replace("100x100bb", "3000x3000bb") \
                                 .replace("100x100",   "3000x3000bb")

        release_date = item.get("releaseDate") or ""
        year         = release_date[:4]

        artist       = item.get("artistName", "Unknown") or "Unknown"
        album_artist = item.get("collectionArtistName") or artist

        return TrackInfo(
            title        = item.get("trackName") or item.get("collectionName", ""),
            artists      = [artist],
            album        = item.get("collectionName", ""),
            album_artist = album_artist,
            year         = year,
            release_date = release_date,
            genre        = item.get("primaryGenreName", ""),
            duration_ms  = item.get("trackTimeMillis", 0),
            cover_url    = artwork,
            source_url   = item.get("trackViewUrl") or item.get("collectionViewUrl", ""),
            platform     = "applemusic",
            track_id     = str(item.get("trackId") or item.get("collectionId", "")),
            track_number = item.get("trackNumber", 0) or 0,
            disc_number  = item.get("discNumber", 0) or 0,
            total_tracks = item.get("trackCount", 0) or 0,
        )

    def _extract_apple_id(self, url: str) -> str | None:
        """Extrae el ID numérico de una URL de Apple Music."""
        # /album/name/123456?i=789 → 789 es el trackId
        m = re.search(r"[?&]i=(\d+)", url)
        if m:
            return m.group(1)
        # /album/name/123456
        m = re.search(r"/(?:album|artist|playlist)/[^/]+/(\d+)", url)
        return m.group(1) if m else None

    # ── MusicProvider interface ────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[TrackInfo]:
        try:
            r = self._session.get(
                self.ITUNES_SEARCH,
                params={"term": query, "media": "music", "entity": "song", "limit": limit},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("results", [])
            return [self._item_to_info(i) for i in items
                    if i.get("wrapperType") == "track"]
        except Exception as e:
            log.error(f"[AppleMusic] Error en búsqueda: {e}")
            return []

    def search_albums(self, query: str, limit: int = 10) -> list[TrackInfo]:
        """Search albums.  The album's collectionViewUrl resolves to all its
        tracks via :meth:`get_tracks_from_url`."""
        try:
            r = self._session.get(
                self.ITUNES_SEARCH,
                params={"term": query, "media": "music", "entity": "album", "limit": limit},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("results", [])
        except Exception as e:
            log.error(f"[AppleMusic] Error en búsqueda de álbumes: {e}")
            return []
        out: list[TrackInfo] = []
        for it in items:
            if it.get("wrapperType") != "collection":
                continue
            art = (it.get("artworkUrl100", "")
                   .replace("100x100bb", "1200x1200bb").replace("100x100", "1200x1200bb"))
            out.append(TrackInfo(
                title        = it.get("collectionName", ""),
                artists      = [it.get("artistName", "Unknown")],
                album        = it.get("collectionName", ""),
                year         = (it.get("releaseDate") or "")[:4],
                cover_url    = art,
                source_url   = it.get("collectionViewUrl", ""),
                platform     = "applemusic",
                is_album     = True,
                track_count  = it.get("trackCount", 0) or 0,
            ))
        return out

    def get_track(self, url_or_id: str) -> TrackInfo | None:
        try:
            aid = (self._extract_apple_id(url_or_id) if url_or_id.startswith("http")
                   else url_or_id)
            if not aid:
                return None
            r = self._session.get(
                self.ITUNES_LOOKUP,
                params={"id": aid},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("results", [])
            if items:
                return self._item_to_info(items[0])
        except Exception as e:
            log.error(f"[AppleMusic] Error al obtener track: {e}")
        return None

    def get_tracks_from_url(self, url: str) -> list[TrackInfo]:
        """
        Procesa URLs de Apple Music.
        - Song:     music.apple.com/es/album/name/id?i=trackid
        - Album:    music.apple.com/es/album/name/id
        - Artist:   music.apple.com/es/artist/name/id
        """
        try:
            # Canción individual (tiene ?i=)
            if re.search(r"[?&]i=\d+", url):
                t = self.get_track(url)
                return [t] if t else []

            aid = self._extract_apple_id(url)
            if not aid:
                # Fallback: buscar por el nombre en la URL
                m = re.search(r"/(?:album|artist)/([^/]+)/", url)
                if m:
                    query = m.group(1).replace("-", " ")
                    return self.search(query, limit=20)
                return []

            r = self._session.get(
                self.ITUNES_LOOKUP,
                params={"id": aid, "entity": "song"},
                timeout=10,
            )
            r.raise_for_status()
            items = r.json().get("results", [])
            # El primer item suele ser el álbum/artista; el resto son tracks
            tracks = [i for i in items if i.get("wrapperType") == "track"]
            return [self._item_to_info(t) for t in tracks]

        except Exception as e:
            log.error(f"[AppleMusic] Error al procesar URL: {e}")
        return []
