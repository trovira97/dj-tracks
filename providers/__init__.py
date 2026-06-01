"""
providers/__init__.py
======================
Strategy interface for music metadata providers.

Defines :class:`TrackInfo` (normalised track data) and
:class:`MusicProvider` (abstract base for Spotify / Apple Music / SoundCloud).
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TrackInfo:
    """
    Normalised track metadata — platform-agnostic.

    All fields are optional except *title* and *artists*, which are
    required to build a meaningful search query and file name.

    Attributes:
        title:       Track title.
        artists:     List of contributing artists.
        album:       Album name (may be empty for singles).
        year:        Release year as a 4-character string, e.g. ``"2023"``.
        genre:       Primary genre string.
        duration_ms: Track length in milliseconds.
        isrc:        International Standard Recording Code.
        cover_url:   HTTP(S) URL of the highest-resolution cover art.
        source_url:  Canonical URL on the originating platform.
        platform:    Provider identifier (``"spotify"``, ``"applemusic"``,
                     ``"soundcloud"``).
        track_id:    Platform-native track identifier.
        extra:       Arbitrary provider-specific extras.
    """

    title:       str
    artists:     List[str]
    album:       str               = ""
    year:        str               = ""
    genre:       str               = ""
    duration_ms: int               = 0
    isrc:        str               = ""
    cover_url:   str               = ""
    source_url:  str               = ""
    platform:    str               = ""
    track_id:    str               = ""
    extra:       Dict[str, Any]    = field(default_factory=dict)

    @property
    def artist_str(self) -> str:
        """Comma-separated artist string, e.g. ``"Artist A, Artist B"``."""
        return ", ".join(self.artists)

    @property
    def duration_str(self) -> str:
        """Human-readable duration string (``"3:47"``), or ``"--:--"``."""
        if not self.duration_ms:
            return "--:--"
        total_s = self.duration_ms // 1000
        return f"{total_s // 60}:{total_s % 60:02d}"


class MusicProvider(ABC):
    """
    Abstract base for all music metadata providers.

    Subclasses implement the three core operations: text search,
    single-track lookup, and URL-based collection retrieval.
    """

    @abstractmethod
    def search(self, query: str, limit: int = 10) -> List[TrackInfo]:
        """
        Search for tracks matching *query*.

        Args:
            query: Artist, title, or freeform search string.
            limit: Maximum number of results to return.

        Returns:
            List of :class:`TrackInfo`, ordered by relevance.
        """
        ...

    @abstractmethod
    def get_track(self, url_or_id: str) -> Optional[TrackInfo]:
        """
        Fetch metadata for a single track by URL or platform ID.

        Returns:
            A :class:`TrackInfo` on success, or ``None`` if not found.
        """
        ...

    @abstractmethod
    def get_tracks_from_url(self, url: str) -> List[TrackInfo]:
        """
        Resolve a URL (track / album / playlist / artist) to a track list.

        Args:
            url: A canonical URL on this provider's platform.

        Returns:
            List of :class:`TrackInfo` objects (one per resolved track).
        """
        ...

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable provider name, e.g. ``"Spotify"``."""
        ...
