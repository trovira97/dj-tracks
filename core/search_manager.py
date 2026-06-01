"""
core/search_manager.py
=======================
Multi-platform search orchestrator.

Implements the **Strategy pattern**: each provider is registered
independently and can be swapped at runtime via :meth:`update_provider`.

Fan-out searches run **concurrently** across all providers using a
thread pool, reducing worst-case wait time from O(n×timeout) to O(timeout).
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

from providers import MusicProvider, TrackInfo
from providers.applemusic_provider  import AppleMusicProvider
from providers.soundcloud_provider  import SoundCloudProvider
from providers.spotify_provider     import SpotifyProvider
from utils.logger     import log
from utils.validators import Platform, detect_platform


class SearchManager:
    """
    Orchestrates multi-platform search and URL resolution.

    Search behaviour:

    - **Named platform**: delegates directly to that provider.
    - **Auto (``Platform.UNKNOWN``)**: fans out to all providers
      concurrently, then deduplicates results by ``artist|title`` key.

    URL resolution:

    1. Detects the platform from the URL.
    2. Dispatches to the matching provider's :meth:`get_tracks_from_url`.
    3. If no provider is configured, returns a minimal stub so the
       downloader can still attempt a yt-dlp fallback.
    """

    def __init__(
        self,
        spotify:     Optional[SpotifyProvider]    = None,
        apple_music: Optional[AppleMusicProvider] = None,
        soundcloud:  Optional[SoundCloudProvider] = None,
    ) -> None:
        self._providers: Dict[Platform, MusicProvider] = {}

        if spotify:
            self._providers[Platform.SPOTIFY]     = spotify
        if apple_music:
            self._providers[Platform.APPLE_MUSIC] = apple_music
        if soundcloud:
            self._providers[Platform.SOUNDCLOUD]  = soundcloud

        # Apple Music is always available (public iTunes Search API).
        if Platform.APPLE_MUSIC not in self._providers:
            self._providers[Platform.APPLE_MUSIC] = AppleMusicProvider()

    # ── Public API ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        platform: Platform = Platform.UNKNOWN,
        limit: int = 20,
    ) -> List[TrackInfo]:
        """
        Search by text query.

        Single-platform requests go directly to that provider.
        Multi-platform (``Platform.UNKNOWN``) runs all providers
        concurrently in a thread pool.

        Args:
            query:    Search string (artist, title, or freeform).
            platform: Restrict to a specific provider, or
                      ``Platform.UNKNOWN`` to search all.
            limit:    Maximum total results to return.

        Returns:
            Deduplicated list of :class:`~providers.TrackInfo`.
        """
        if platform != Platform.UNKNOWN:
            provider = self._providers.get(platform)
            if not provider:
                log.warning(f"[SearchManager] Proveedor no disponible: {platform}")
                return []
            return provider.search(query, limit=limit)

        if not self._providers:
            return []

        per_provider = max(1, limit // len(self._providers) + 1)
        results: List[TrackInfo] = []

        with ThreadPoolExecutor(
            max_workers=len(self._providers),
            thread_name_prefix="dj-search",
        ) as pool:
            futures = {
                pool.submit(p.search, query, per_provider): plat
                for plat, p in self._providers.items()
            }
            for fut in as_completed(futures):
                plat = futures[fut]
                try:
                    results.extend(fut.result())
                except Exception as exc:
                    log.error(f"[SearchManager] Error en {plat}: {exc}")

        return self._deduplicate(results)[:limit]

    def resolve_url(self, url: str) -> List[TrackInfo]:
        """
        Detect the platform from *url* and return its tracks.

        Args:
            url: A canonical URL from any supported platform.

        Returns:
            List of :class:`~providers.TrackInfo`, empty on failure.
        """
        platform = detect_platform(url)

        if platform == Platform.UNKNOWN:
            log.warning(f"[SearchManager] URL no reconocida: {url}")
            return []

        provider = self._providers.get(platform)
        if not provider:
            log.warning(f"[SearchManager] Sin proveedor para {platform} — devolviendo stub")
            return [TrackInfo(
                title      = url.split("/")[-1].split("?")[0] or url,
                artists    = ["Unknown"],
                source_url = url,
                platform   = platform.value,
            )]

        return provider.get_tracks_from_url(url)

    def update_provider(self, platform: Platform, provider: MusicProvider) -> None:
        """Replace or register a provider at runtime (thread-safe)."""
        self._providers[platform] = provider
        log.info(f"[SearchManager] Proveedor actualizado: {platform}")

    def provider_for(self, platform: Platform) -> Optional[MusicProvider]:
        """Return the provider registered for *platform*, or ``None``."""
        return self._providers.get(platform)

    @property
    def available_platforms(self) -> List[str]:
        """List of platform value strings for registered providers."""
        return [p.value for p in self._providers]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _deduplicate(tracks: List[TrackInfo]) -> List[TrackInfo]:
        """Remove duplicate tracks (same artist + title, case-insensitive)."""
        seen: set[str] = set()
        unique: List[TrackInfo] = []
        for track in tracks:
            key = f"{track.artist_str.lower()}|{track.title.lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(track)
        return unique
