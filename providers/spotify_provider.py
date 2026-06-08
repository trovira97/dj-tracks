"""
providers/spotify_provider.py
==============================
Spotify metadata provider via spotipy.

Handles search, single tracks, albums, playlists, and artist top tracks.
"""
from __future__ import annotations

from typing import List, Optional

from providers import MusicProvider, TrackInfo
from utils.logger import log
from utils.validators import extract_spotify_id

# Maximum tracks to return from a single playlist / album fetch.
_PLAYLIST_LIMIT = 300


class SpotifyProvider(MusicProvider):

    def __init__(self, client_id: str, client_secret: str) -> None:
        self._client_id     = client_id
        self._client_secret = client_secret
        self._sp            = None
        self._available     = False
        self._init()

    def _init(self) -> None:
        if not (self._client_id and self._client_secret):
            log.warning("[Spotify] Sin credenciales — funcionalidad limitada")
            return
        try:
            import spotipy
            from spotipy.oauth2 import SpotifyClientCredentials
            self._sp = spotipy.Spotify(
                client_credentials_manager=SpotifyClientCredentials(
                    client_id=self._client_id,
                    client_secret=self._client_secret,
                ),
                requests_timeout=10,
            )
            self._available = True
            log.info("[Spotify] Cliente inicializado correctamente")
        except Exception as exc:
            log.error(f"[Spotify] Error al inicializar: {exc}")

    @property
    def name(self) -> str:
        return "Spotify"

    @property
    def available(self) -> bool:
        return self._available

    # ── Conversion ────────────────────────────────────────────────────────────

    def _track_to_info(self, t: dict) -> Optional[TrackInfo]:
        """
        Convert a Spotify track dict to TrackInfo with full metadata.

        Returns None if the dict is falsy or missing required fields
        (happens with deleted/unavailable tracks in playlists).
        """
        if not t or not isinstance(t, dict):
            return None
        if not t.get("id"):
            return None
        try:
            artists = [a["name"] for a in t.get("artists", []) if a.get("name")]
            album   = t.get("album") or {}
            images  = album.get("images") or []
            # Spotify returns images sorted largest-first (640x640 → 300x300 → 64x64).
            cover   = images[0]["url"] if images else ""
            release_date = album.get("release_date") or ""
            year         = release_date[:4]
            isrc         = (t.get("external_ids") or {}).get("isrc", "")

            album_artists = [a["name"] for a in (album.get("artists") or []) if a.get("name")]
            album_artist  = ", ".join(album_artists) if album_artists else ""

            return TrackInfo(
                title        = t.get("name", "") or "Unknown",
                artists      = artists or ["Unknown"],
                album        = album.get("name", ""),
                album_artist = album_artist,
                year         = year,
                release_date = release_date,
                isrc         = isrc,
                cover_url    = cover,
                duration_ms  = t.get("duration_ms", 0),
                source_url   = (t.get("external_urls") or {}).get("spotify", ""),
                platform     = "spotify",
                track_id     = t.get("id", ""),
                track_number = t.get("track_number", 0) or 0,
                disc_number  = t.get("disc_number", 0) or 0,
                total_tracks = album.get("total_tracks", 0) or 0,
            )
        except Exception as exc:
            log.warning(f"[Spotify] No se pudo convertir track: {exc}")
            return None

    # ── MusicProvider ─────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> List[TrackInfo]:
        if not self._available:
            return []
        try:
            results = self._sp.search(q=query, type="track", limit=min(limit, 50))
            tracks  = (results or {}).get("tracks", {}).get("items", [])
            return [ti for t in tracks if (ti := self._track_to_info(t))]
        except Exception as exc:
            log.error(f"[Spotify] Error en búsqueda: {exc}")
            return []

    def search_albums(self, query: str, limit: int = 10) -> List[TrackInfo]:
        """Search albums.  The album URL resolves to all tracks via
        :meth:`get_tracks_from_url`."""
        if not self._available:
            return []
        try:
            results = self._sp.search(q=query, type="album", limit=min(limit, 50))
            albums  = (results or {}).get("albums", {}).get("items", [])
        except Exception as exc:
            log.error(f"[Spotify] Error en búsqueda de álbumes: {exc}")
            return []
        out: List[TrackInfo] = []
        for al in albums:
            if not al or not al.get("id"):
                continue
            images = al.get("images") or []
            out.append(TrackInfo(
                title        = al.get("name", "Unknown"),
                artists      = [a["name"] for a in al.get("artists", []) if a.get("name")] or ["Unknown"],
                album        = al.get("name", ""),
                year         = (al.get("release_date") or "")[:4],
                cover_url    = images[0]["url"] if images else "",
                source_url   = (al.get("external_urls") or {}).get("spotify", ""),
                platform     = "spotify",
                is_album     = True,
                track_count  = al.get("total_tracks", 0) or 0,
            ))
        return out

    def get_track(self, url_or_id: str) -> Optional[TrackInfo]:
        if not self._available:
            return None
        try:
            tid = extract_spotify_id(url_or_id) or url_or_id
            t   = self._sp.track(tid)
            return self._track_to_info(t)
        except Exception as exc:
            log.error(f"[Spotify] Error al obtener track: {exc}")
            return None

    def get_tracks_from_url(self, url: str) -> List[TrackInfo]:
        if not self._available:
            return []
        try:
            # ── Single track ──────────────────────────────────────────────────
            if "/track/" in url:
                t = self.get_track(url)
                return [t] if t else []

            # ── Album ─────────────────────────────────────────────────────────
            if "/album/" in url:
                aid   = extract_spotify_id(url)
                album = self._sp.album(aid)
                album_name = album.get("name", "")
                images     = album.get("images") or []
                cover      = images[0]["url"] if images else ""
                year       = (album.get("release_date") or "")[:4]

                raw_tracks = album.get("tracks", {}).get("items", [])
                # Paginate if album has more tracks
                while album.get("tracks", {}).get("next"):
                    album   = self._sp.next(album["tracks"])
                    raw_tracks.extend(album.get("items", []))

                total_tracks  = album.get("total_tracks", len(raw_tracks))
                album_artists = [a["name"] for a in (album.get("artists") or []) if a.get("name")]
                album_artist  = ", ".join(album_artists)

                result = []
                for t in raw_tracks[:_PLAYLIST_LIMIT]:
                    if not t or not t.get("id"):
                        continue
                    artists = [a["name"] for a in t.get("artists", []) if a.get("name")]
                    result.append(TrackInfo(
                        title        = t.get("name", "") or "Unknown",
                        artists      = artists or ["Unknown"],
                        album        = album_name,
                        album_artist = album_artist,
                        year         = year,
                        cover_url    = cover,
                        duration_ms  = t.get("duration_ms", 0),
                        source_url   = (t.get("external_urls") or {}).get("spotify", ""),
                        platform     = "spotify",
                        track_id     = t.get("id", ""),
                        track_number = t.get("track_number", 0) or 0,
                        disc_number  = t.get("disc_number", 0) or 0,
                        total_tracks = total_tracks,
                    ))
                log.info(f"[Spotify] Album: {len(result)} pistas")
                return result

            # ── Playlist ──────────────────────────────────────────────────────
            if "/playlist/" in url:
                pid    = extract_spotify_id(url)
                items  = []
                offset = 0
                while len(items) < _PLAYLIST_LIMIT:
                    page = self._sp.playlist_tracks(
                        pid, offset=offset, limit=100,
                        fields="items(track(id,name,artists,album,duration_ms,"
                               "external_urls,external_ids)),next"
                    )
                    batch = page.get("items", [])
                    items.extend(batch)
                    if not page.get("next") or not batch:
                        break
                    offset += 100

                tracks = []
                for i in items[:_PLAYLIST_LIMIT]:
                    t  = i.get("track") if isinstance(i, dict) else None
                    ti = self._track_to_info(t)
                    if ti:
                        tracks.append(ti)
                log.info(f"[Spotify] Playlist: {len(tracks)} pistas (de {len(items)} entradas)")
                return tracks

            # ── Artist top tracks ─────────────────────────────────────────────
            if "/artist/" in url:
                aid    = extract_spotify_id(url)
                result = self._sp.artist_top_tracks(aid)
                return [ti for t in result.get("tracks", [])
                        if (ti := self._track_to_info(t))]

        except Exception as exc:
            log.error(f"[Spotify] Error al procesar URL: {exc}")
        return []

    def update_credentials(self, client_id: str, client_secret: str) -> None:
        self._client_id     = client_id
        self._client_secret = client_secret
        self._available     = False
        self._sp            = None
        self._init()
