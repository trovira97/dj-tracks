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

from providers import MusicProvider, TrackInfo
from providers.applemusic_provider import AppleMusicProvider
from providers.bandcamp_provider import BandcampProvider
from providers.soundcloud_provider import SoundCloudProvider
from providers.spotify_provider import SpotifyProvider
from providers.youtube_provider import YouTubeProvider
from utils.logger import log
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
        spotify:     SpotifyProvider | None    = None,
        apple_music: AppleMusicProvider | None = None,
        soundcloud:  SoundCloudProvider | None = None,
        bandcamp:    BandcampProvider | None   = None,
        youtube:     YouTubeProvider | None    = None,
    ) -> None:
        self._providers: dict[Platform, MusicProvider] = {}

        if spotify:
            self._providers[Platform.SPOTIFY]     = spotify
        if apple_music:
            self._providers[Platform.APPLE_MUSIC] = apple_music
        if soundcloud:
            self._providers[Platform.SOUNDCLOUD]  = soundcloud
        if bandcamp:
            self._providers[Platform.BANDCAMP]    = bandcamp
        if youtube:
            self._providers[Platform.YOUTUBE]     = youtube

        # Apple Music, Bandcamp, and YouTube are always available
        # (no credentials needed for any of them).
        if Platform.APPLE_MUSIC not in self._providers:
            self._providers[Platform.APPLE_MUSIC] = AppleMusicProvider()
        if Platform.BANDCAMP not in self._providers:
            self._providers[Platform.BANDCAMP] = BandcampProvider()
        if Platform.YOUTUBE not in self._providers:
            self._providers[Platform.YOUTUBE] = YouTubeProvider()

    # ── Public API ─────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        platform: Platform = Platform.UNKNOWN,
        limit: int = 20,
        include_albums: bool = True,
    ) -> list[TrackInfo]:
        """
        Search by text query for tracks (and optionally whole albums).

        Single-platform requests go directly to that provider.
        Multi-platform (``Platform.UNKNOWN``) runs all providers
        concurrently in a thread pool.  Album results (``is_album``) are
        listed first.

        Args:
            query:          Search string (artist, title, or freeform).
            platform:       Restrict to a provider, or ``UNKNOWN`` for all.
            limit:          Maximum total track results.
            include_albums: Also return album/set results (shown first).

        Returns:
            Deduplicated list of :class:`~providers.TrackInfo`.
        """
        if platform != Platform.UNKNOWN:
            provider = self._providers.get(platform)
            if not provider:
                log.warning(f"[SearchManager] Proveedor no disponible: {platform}")
                return []
            albums = []
            if include_albums and hasattr(provider, "search_albums"):
                try:
                    albums = provider.search_albums(query, limit=max(4, limit // 3))
                except Exception as exc:
                    log.error(f"[SearchManager] Álbumes {platform}: {exc}")
            tracks = self._deduplicate(provider.search(query, limit=limit))
            return self._deduplicate(albums) + tracks

        if not self._providers:
            return []

        per_provider = max(limit, 10)
        # Build the task list: album searches first (so they rank on top),
        # then track searches.
        tasks = []
        if include_albums:
            for plat, p in self._providers.items():
                if hasattr(p, "search_albums"):
                    tasks.append(("album", plat, lambda p=p: p.search_albums(query, max(4, limit // 3))))
        for plat, p in self._providers.items():
            tasks.append(("track", plat, lambda p=p: p.search(query, per_provider)))

        albums: list[TrackInfo] = []
        tracks: list[TrackInfo] = []
        with ThreadPoolExecutor(
            max_workers=max(2, len(tasks)),
            thread_name_prefix="dj-search",
        ) as pool:
            futures = {pool.submit(fn): kind for kind, plat, fn in tasks}
            for fut in as_completed(futures):
                try:
                    res = fut.result()
                except Exception as exc:
                    log.error(f"[SearchManager] Error: {exc}")
                    continue
                (albums if futures[fut] == "album" else tracks).extend(res)

        albums = self._deduplicate(albums)[:max(4, limit // 3)]
        tracks = self._deduplicate(tracks)
        return (albums + tracks)[:limit + len(albums)]

    def resolve_url(self, url: str) -> list[TrackInfo]:
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

    def provider_for(self, platform: Platform) -> MusicProvider | None:
        """Return the provider registered for *platform*, or ``None``."""
        return self._providers.get(platform)

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _deduplicate(tracks: list[TrackInfo]) -> list[TrackInfo]:
        """Remove duplicates (same artist + title, case-insensitive).  Albums
        and tracks are kept in separate namespaces so an album doesn't dedup
        against a single track of the same name."""
        seen: set[str] = set()
        unique: list[TrackInfo] = []
        for track in tracks:
            tag = "alb" if getattr(track, "is_album", False) else "trk"
            key = f"{tag}|{track.artist_str.lower()}|{track.title.lower()}"
            if key not in seen:
                seen.add(key)
                unique.append(track)
        return unique
