"""
providers/soundcloud_provider.py
=================================
SoundCloud metadata provider using the internal API v2.

No API key required: auto-extracts a public client_id from SoundCloud's
own JavaScript assets when none is configured.
"""
from __future__ import annotations

import re

import requests

from providers import MusicProvider, TrackInfo
from utils.logger import log

_PLAYLIST_LIMIT = 200


class SoundCloudProvider(MusicProvider):
    """
    SoundCloud metadata provider.

    Uses the public SoundCloud API v2.  When no ``client_id`` is supplied,
    one is extracted automatically from SoundCloud's JavaScript bundle.
    Note: scraping the client_id is a best-effort approach and may break
    if SoundCloud changes their asset structure.
    """

    HOME_URL  = "https://soundcloud.com"
    API_BASE  = "https://api-v2.soundcloud.com"
    ASSET_RE  = re.compile(r'src="(https://a-v2\.sndcdn\.com/assets/[^"]+\.js)"')
    CLIENT_RE = re.compile(r'client_id:"([^"]+)"')

    def __init__(self, client_id: str = "") -> None:
        self._client_id = client_id if self._valid_id(client_id) else ""
        self._session   = requests.Session()
        self._session.headers["User-Agent"] = (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 Chrome/120.0 Safari/537.36"
        )
        self._available = True
        log.info(
            "[SoundCloud] Cliente inicializado con client_id configurado"
            if self._client_id else
            "[SoundCloud] Cliente iniciado — client_id automático bajo demanda"
        )

    @property
    def name(self) -> str:
        return "SoundCloud"

    @property
    def available(self) -> bool:
        return self._available

    @staticmethod
    def _valid_id(cid: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_-]{20,}", cid or ""))

    # ── Client ID management ──────────────────────────────────────────────────

    def _ensure_client_id(self) -> bool:
        if self._valid_id(self._client_id):
            return True
        try:
            home    = self._session.get(self.HOME_URL, timeout=10)
            home.raise_for_status()
            scripts = self.ASSET_RE.findall(home.text)
            for url in scripts[:12]:
                js = self._session.get(url, timeout=10)
                js.raise_for_status()
                m  = self.CLIENT_RE.search(js.text)
                if m:
                    self._client_id = m.group(1)
                    log.info("[SoundCloud] client_id automático obtenido")
                    return True
            log.warning("[SoundCloud] No se pudo encontrar client_id en assets de SoundCloud")
        except Exception as exc:
            log.warning(f"[SoundCloud] No se pudo obtener client_id: {exc}")
        return False

    def _api(self, path: str, params: dict | None = None) -> dict | None:
        if not self._ensure_client_id():
            return None
        p = dict(params or {})
        p["client_id"] = self._client_id
        try:
            r = self._session.get(f"{self.API_BASE}{path}", params=p, timeout=15)
            r.raise_for_status()
            return r.json()
        except Exception as exc:
            log.error(f"[SoundCloud] API error {path}: {exc}")
            return None

    # ── Conversion ────────────────────────────────────────────────────────────

    def _to_info(self, t: dict) -> TrackInfo | None:
        """Convert a SoundCloud API track dict to :class:`TrackInfo`."""
        if not isinstance(t, dict) or not t:
            return None
        try:
            # Request the original (uncropped) artwork instead of the 500×500
            # downscale.  The SC CDN serves whatever suffix you provide; -original
            # returns the source upload at its native resolution.
            artwork = (t.get("artwork_url") or "").replace("-large", "-original")

            user    = t.get("user") or {}
            artist  = (user.get("username") if isinstance(user, dict) else None) or "Unknown"
            title   = t.get("title") or "Unknown"

            # Many SoundCloud tracks are titled "Artist - Title" by convention.
            artists = [artist]
            if " - " in title:
                a_part, t_part = title.split(" - ", 1)
                if a_part.strip():
                    artists = [a_part.strip()]
                    title   = t_part.strip()

            release_date = t.get("release_date") or t.get("created_at", "")[:10]
            year         = release_date[:4] if release_date else ""

            return TrackInfo(
                title        = title,
                artists      = artists,
                album        = "",
                year         = year,
                release_date = release_date,
                genre        = t.get("genre") or "",
                duration_ms  = t.get("duration") or 0,
                cover_url    = artwork,
                source_url   = t.get("permalink_url") or "",
                platform     = "soundcloud",
                track_id     = str(t.get("id") or ""),
            )
        except Exception as exc:
            log.warning(f"[SoundCloud] No se pudo convertir track: {exc}")
            return None

    # ── MusicProvider ─────────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[TrackInfo]:
        try:
            data  = self._api("/search/tracks", {"q": query, "limit": limit})
            items = (data or {}).get("collection", [])
            return [ti for t in items[:limit] if (ti := self._to_info(t))]
        except Exception as exc:
            log.error(f"[SoundCloud] Error en búsqueda: {exc}")
            return []

    def search_albums(self, query: str, limit: int = 10) -> list[TrackInfo]:
        """Search SoundCloud sets/playlists.  The set URL resolves to all its
        tracks via :meth:`get_tracks_from_url`."""
        try:
            data  = self._api("/search/playlists", {"q": query, "limit": limit})
            items = (data or {}).get("collection", [])
        except Exception as exc:
            log.error(f"[SoundCloud] Error en búsqueda de álbumes: {exc}")
            return []
        out: list[TrackInfo] = []
        for pl in items[:limit]:
            if not isinstance(pl, dict):
                continue
            user   = pl.get("user") or {}
            artist = (user.get("username") if isinstance(user, dict) else None) or "Unknown"
            artwork = (pl.get("artwork_url") or "").replace("-large", "-t500x500")
            out.append(TrackInfo(
                title       = pl.get("title") or "Unknown",
                artists     = [artist],
                album       = pl.get("title") or "",
                cover_url   = artwork,
                source_url  = pl.get("permalink_url") or "",
                platform    = "soundcloud",
                is_album    = True,
                track_count = pl.get("track_count", 0) or 0,
            ))
        return out

    def get_track(self, url_or_id: str) -> TrackInfo | None:
        try:
            if url_or_id.startswith("http"):
                data = self._api("/resolve", {"url": url_or_id})
            else:
                data = self._api(f"/tracks/{url_or_id}")
            return self._to_info(data) if isinstance(data, dict) else None
        except Exception as exc:
            log.error(f"[SoundCloud] Error al obtener track: {exc}")
            return None

    def get_tracks_from_url(self, url: str) -> list[TrackInfo]:
        try:
            resource = self._api("/resolve", {"url": url})
            if not isinstance(resource, dict):
                return []

            kind = resource.get("kind", "")

            if kind == "track":
                ti = self._to_info(resource)
                return [ti] if ti else []

            if kind in ("playlist", "system-playlist"):
                raw     = resource.get("tracks") or []
                missing = [t for t in raw if not t.get("title")]

                if missing:
                    ids       = ",".join(str(t["id"]) for t in missing if t.get("id"))
                    full_data = self._api("/tracks", {"ids": ids}) if ids else []
                    full_map  = {str(t["id"]): t for t in (full_data or [])}
                    raw = [
                        full_map.get(str(t.get("id")), t) if not t.get("title") else t
                        for t in raw
                    ]

                tracks = [ti for t in raw[:_PLAYLIST_LIMIT] if (ti := self._to_info(t))]
                log.info(f"[SoundCloud] Playlist: {len(tracks)} pistas")
                return tracks

            if kind == "user":
                uid  = resource.get("id")
                data = self._api(f"/users/{uid}/tracks", {"limit": 50})
                return [ti for t in (data or {}).get("collection", [])
                        if (ti := self._to_info(t))]

        except Exception as exc:
            log.error(f"[SoundCloud] Error al procesar URL: {exc}")
        return []
