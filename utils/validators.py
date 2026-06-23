"""
utils/validators.py
====================
URL detection, platform identification, and input sanitisation helpers.
"""
from __future__ import annotations

import re
from enum import Enum
from typing import Optional


class Platform(str, Enum):
    """Supported music platforms."""

    SPOTIFY     = "spotify"
    APPLE_MUSIC = "applemusic"
    SOUNDCLOUD  = "soundcloud"
    BANDCAMP    = "bandcamp"
    YOUTUBE     = "youtube"
    UNKNOWN     = "unknown"


class ContentType(str, Enum):
    """Type of content represented by a URL."""

    TRACK    = "track"
    ALBUM    = "album"
    PLAYLIST = "playlist"
    ARTIST   = "artist"
    UNKNOWN  = "unknown"


# Windows reserved device names that cannot be used as filenames.
_WINDOWS_RESERVED: frozenset[str] = frozenset({
    "CON", "PRN", "AUX", "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
})

# Characters illegal in Windows and Unix filenames.
_ILLEGAL_CHARS_RE = re.compile(r'[\\/:*?"<>|]')


def detect_platform(url: str) -> Platform:
    """
    Identify the :class:`Platform` from a URL.

    Args:
        url: Any HTTP(S) URL string.

    Returns:
        The matching :class:`Platform`, or ``Platform.UNKNOWN``.
    """
    lower = url.lower()
    if "spotify.com" in lower:
        return Platform.SPOTIFY
    if "music.apple.com" in lower:
        return Platform.APPLE_MUSIC
    if "soundcloud.com" in lower:
        return Platform.SOUNDCLOUD
    if "bandcamp.com" in lower:
        return Platform.BANDCAMP
    if ("youtube.com" in lower or "youtu.be" in lower
            or "music.youtube.com" in lower):
        return Platform.YOUTUBE
    return Platform.UNKNOWN


def detect_content_type(url: str) -> ContentType:
    """
    Infer the :class:`ContentType` from a platform URL.

    Args:
        url: A canonical URL from a supported platform.

    Returns:
        The detected :class:`ContentType`, or ``ContentType.UNKNOWN``.
    """
    m = re.search(
        r"spotify\.com/(?:intl-[a-z]{2}/)?(track|album|playlist|artist)/",
        url,
    )
    if m:
        return ContentType(m.group(1))

    if re.search(r"\?i=\d+", url):
        return ContentType.TRACK
    if "/album/" in url:
        return ContentType.ALBUM
    if "/artist/" in url:
        return ContentType.ARTIST
    if "/playlist/" in url:
        return ContentType.PLAYLIST

    # YouTube — playlist takes precedence over the video id when both present
    if "list=" in url:
        return ContentType.PLAYLIST
    if "youtu.be/" in url or "youtube.com/watch" in url or "youtube.com/shorts" in url:
        return ContentType.TRACK

    return ContentType.UNKNOWN


def is_valid_url(url: str) -> bool:
    """Return ``True`` if *url* starts with ``http://`` or ``https://``."""
    return url.startswith(("http://", "https://"))


def extract_spotify_id(url: str) -> Optional[str]:
    """
    Extract the Spotify resource ID from a URL.

    Args:
        url: A ``open.spotify.com`` or ``spotify.com`` URL.

    Returns:
        The Base62 resource ID string, or ``None``.
    """
    m = re.search(
        r"spotify\.com/(?:intl-[a-z]{2}/)?(?:track|album|playlist|artist)/([A-Za-z0-9]+)",
        url,
    )
    return m.group(1) if m else None


def sanitize_filename(name: str, max_length: int = 200) -> str:
    """
    Strip characters that are illegal in file-system names.

    - Removes ``\\ / : * ? " < > |``
    - Collapses surrounding dots/spaces
    - Rejects Windows reserved device names (CON, NUL, COM1…)
    - Truncates to *max_length* characters
    - Falls back to ``"unknown"`` if the result is empty

    Args:
        name:       Raw filename candidate.
        max_length: Maximum allowed character count.

    Returns:
        A safe, non-empty filename string.
    """
    name = _ILLEGAL_CHARS_RE.sub("", name)
    name = name.strip(". ")

    # Prefix Windows reserved names so they become valid.
    if name.upper() in _WINDOWS_RESERVED:
        name = f"_{name}"

    return (name[:max_length] if name else "unknown")
