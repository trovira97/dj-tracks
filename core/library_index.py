"""
core/library_index.py
======================
Fast in-memory index of the user's local library, backing the
"already-in-library" badge and the "download only missing tracks"
button in the playlist import flow.

Sources
-------
1. ``HistoryManager`` — authoritative record of every successful download.
2. On-disk scan of the downloads folder (fallback for tracks downloaded
   outside the app or when history was cleared).

Matching
--------
Tracks are keyed on a normalised ``(artist, title)`` tuple:

- lowercase
- accent-folded
- feat./remix suffixes stripped
- whitespace collapsed

This is intentionally lossy — the goal is to catch "same song, slightly
different tags" (e.g. "Artist" vs "Artist ft. Someone") without demanding
byte-for-byte metadata identity.
"""
from __future__ import annotations

import re
import threading
from pathlib import Path

from utils.logger import log

# ── Normalisation ─────────────────────────────────────────────────────────

_ACCENTS = str.maketrans({
    "á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n",
    "ü": "u", "à": "a", "è": "e", "ì": "i", "ò": "o", "ù": "u",
    "â": "a", "ê": "e", "î": "i", "ô": "o", "û": "u", "ç": "c",
})

# Common feat./remix markers that make identical songs look different.
_FEAT_RE = re.compile(
    r"\s*[\(\[]\s*(?:feat|ft|con|with|prod|remix|edit|extended|radio)"
    r"\.?\s*[^)\]]*[\)\]]",
    re.IGNORECASE,
)
_TRAILING_FEAT_RE = re.compile(
    r"\s+(?:feat|ft|con|with)\.?\s+.+$",
    re.IGNORECASE,
)
_WS_RE = re.compile(r"\s+")


def _normalise(text: str) -> str:
    """Lowercase + strip accents + strip feat/remix markers + collapse WS."""
    if not text:
        return ""
    t = text.lower().translate(_ACCENTS)
    t = _FEAT_RE.sub("", t)
    t = _TRAILING_FEAT_RE.sub("", t)
    # Strip punctuation that varies between platforms.
    t = re.sub(r"[^\w\s-]", "", t)
    t = _WS_RE.sub(" ", t).strip()
    return t


def track_key(artist: str, title: str) -> tuple[str, str]:
    """Canonical dedup key.  Use for both indexing and lookups."""
    return (_normalise(artist), _normalise(title))


# ── Index ─────────────────────────────────────────────────────────────────

class LibraryIndex:
    """Fast in-memory dedup index.

    Rebuild on demand (cheap — a few hundred entries at most for a normal
    user's library).  Thread-safe.  A single instance is shared across
    the app; refresh it whenever a download completes.
    """

    def __init__(self) -> None:
        self._keys: set[tuple[str, str]] = set()
        self._lock = threading.Lock()

    # ── Build ─────────────────────────────────────────────────────────────

    def rebuild(self, history_manager=None, extra_scan_dirs=None) -> int:
        """Rebuild the index from HistoryManager + optional disk scan.

        Args:
            history_manager: optional HistoryManager; if provided, all
                ``done`` records contribute to the index.
            extra_scan_dirs: iterable of paths to scan for audio files
                whose ``artist - title`` filename pattern will be indexed.

        Returns:
            Number of entries in the rebuilt index.
        """
        keys: set[tuple[str, str]] = set()

        if history_manager is not None:
            try:
                for r in history_manager.all():
                    if r.status != "done":
                        continue
                    keys.add(track_key(r.artist, r.title))
            except Exception as exc:
                log.warning(f"[LibraryIndex] history scan failed: {exc}")

        for d in extra_scan_dirs or []:
            try:
                keys.update(self._scan_dir(Path(d)))
            except Exception as exc:
                log.warning(f"[LibraryIndex] scan of {d} failed: {exc}")

        with self._lock:
            self._keys = keys

        log.info(f"[LibraryIndex] rebuilt — {len(keys)} unique tracks")
        return len(keys)

    @staticmethod
    def _scan_dir(root: Path) -> set[tuple[str, str]]:
        """Extract ``(artist, title)`` from ``Artist - Title.ext`` filenames."""
        keys: set[tuple[str, str]] = set()
        if not root.exists() or not root.is_dir():
            return keys
        audio_exts = {".mp3", ".m4a", ".flac", ".wav", ".aac", ".ogg", ".opus"}
        for p in root.rglob("*"):
            if not p.is_file() or p.suffix.lower() not in audio_exts:
                continue
            stem = p.stem
            # Expected pattern: "Artist - Title" (possibly with " [quality]" suffix).
            stem = re.sub(r"\s*\[[^\]]*\]\s*$", "", stem)
            parts = stem.split(" - ", 1)
            if len(parts) == 2:
                keys.add(track_key(parts[0], parts[1]))
        return keys

    # ── Query ─────────────────────────────────────────────────────────────

    def contains(self, artist: str, title: str) -> bool:
        """True if a matching track was found by the last rebuild."""
        with self._lock:
            return track_key(artist, title) in self._keys

    def missing(self, tracks) -> list:
        """Return the subset of *tracks* NOT yet in the library.

        Accepts any iterable of objects exposing ``artist_str`` and ``title``
        attributes (i.e. :class:`~providers.TrackInfo`).
        """
        with self._lock:
            keys_snapshot = set(self._keys)
        result = []
        for t in tracks:
            artist = getattr(t, "artist_str", "") or ""
            title  = getattr(t, "title", "") or ""
            if track_key(artist, title) not in keys_snapshot:
                result.append(t)
        return result

    def __len__(self) -> int:
        with self._lock:
            return len(self._keys)


# ── Module-level singleton ────────────────────────────────────────────────

_singleton: LibraryIndex | None = None


def get_library_index() -> LibraryIndex:
    """Return the shared :class:`LibraryIndex` instance."""
    global _singleton
    if _singleton is None:
        _singleton = LibraryIndex()
    return _singleton
