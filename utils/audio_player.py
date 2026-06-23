"""
utils/audio_player.py
======================
Lightweight singleton audio player backed by pygame.

Designed for *preview* playback inside DJ Tracks:
- One song at a time (pressing ▶ on another row stops the previous).
- Pause / resume / stop / seek (when the format allows it).
- No-op gracefully when pygame is unavailable so the UI degrades
  cleanly instead of crashing.

The pygame mixer is initialised lazily — that way nothing happens on
import and the cost is paid only the first time the user clicks play.
"""
from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Callable, Optional

log = logging.getLogger("dj_tracks.player")


def _read_duration(filepath: Path) -> float:
    """Return duration in seconds, or 0.0 if it can't be determined."""
    try:
        from mutagen import File as MutagenFile
        info = MutagenFile(str(filepath))
        if info is not None and getattr(info, "info", None) is not None:
            return float(info.info.length or 0.0)
    except Exception:
        pass
    return 0.0


def _read_tags(filepath: Path) -> tuple[str, str]:
    """Return (title, artist) from embedded tags, falling back to the
    "Artist - Title" filename pattern used by the downloader."""
    title, artist = "", ""
    try:
        from mutagen import File as MutagenFile
        info = MutagenFile(str(filepath), easy=True)
        if info is not None and info.tags:
            title  = (info.tags.get("title", [""])  or [""])[0] or ""
            artist = (info.tags.get("artist", [""]) or [""])[0] or ""
    except Exception:
        pass
    if not title or not artist:
        stem = filepath.stem
        if " - " in stem:
            parts = stem.split(" - ", 1)
            artist = artist or parts[0].strip()
            title  = title  or parts[1].strip()
        else:
            title = title or stem
    return title, artist


def _read_cover_bytes(filepath: Path) -> Optional[bytes]:
    """Return the raw image bytes of the embedded album art, or None."""
    try:
        from mutagen import File as MutagenFile
        info = MutagenFile(str(filepath))
        if info is None:
            return None
        # MP3 / ID3
        for key in (info.tags or {}):
            if key.startswith("APIC"):
                return info.tags[key].data
        # MP4 / M4A
        covers = getattr(info, "tags", None)
        if covers and "covr" in covers:
            data = covers["covr"]
            if data:
                return bytes(data[0])
        # Vorbis (FLAC/OGG)
        pics = getattr(info, "pictures", None)
        if pics:
            return pics[0].data
    except Exception:
        pass
    return None


class AudioPlayer:
    """Tiny pygame-backed preview player.  Thread-safe singleton."""

    _instance: "Optional[AudioPlayer]" = None
    _instance_lock = threading.Lock()

    @classmethod
    def get(cls) -> "AudioPlayer":
        with cls._instance_lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def __init__(self) -> None:
        self._lock     = threading.Lock()
        self._ready    = False           # mixer initialised?
        self._current: Optional[Path] = None
        self._paused   = False
        self._volume   = 0.8             # 0.0 — 1.0
        self._duration = 0.0             # seconds, 0 = unknown
        self._start_pos = 0.0            # seek offset baked in on play(start=)
        self._title    = ""
        self._artist   = ""
        self._cover_bytes: Optional[bytes] = None
        # Queue support (for prev/next).  Filled by the UI layer with the
        # list of history paths so the player can walk it.
        self._queue: list[Path] = []
        self._queue_idx: int    = -1
        self._on_state_change: list[Callable] = []

    @property
    def available(self) -> bool:
        """True if pygame is importable on this machine."""
        try:
            import pygame                 # noqa: F401
            return True
        except Exception:
            return False

    def _ensure_mixer(self) -> bool:
        """Lazily init the pygame mixer.  Idempotent."""
        if self._ready:
            return True
        try:
            import pygame
            pygame.mixer.init()
            self._ready = True
            return True
        except Exception as exc:
            log.warning(f"[Player] No se pudo iniciar el mixer: {exc}")
            return False

    # ── Public API ───────────────────────────────────────────────────────────

    def play(self, filepath: Path, start: float = 0.0) -> bool:
        """
        Play *filepath* from *start* seconds.  Replaces whatever was playing.

        Returns:
            ``True`` if playback started, ``False`` otherwise.
        """
        filepath = Path(filepath) if not isinstance(filepath, Path) else filepath
        if not filepath.exists():
            log.warning(f"[Player] Archivo no encontrado: {filepath}")
            return False
        with self._lock:
            if not self._ensure_mixer():
                return False
            try:
                import pygame
                pygame.mixer.music.load(str(filepath))
                pygame.mixer.music.set_volume(self._volume)
                pygame.mixer.music.play(start=max(0.0, start))
                self._current   = filepath
                self._paused    = False
                self._start_pos = max(0.0, start)
                # Only re-read tags/duration/cover when the file actually
                # changed — seek() calls play() under the hood and we don't
                # want to re-parse the file every time the slider moves.
                if start == 0.0:
                    self._duration    = _read_duration(filepath)
                    self._title, self._artist = _read_tags(filepath)
                    self._cover_bytes = _read_cover_bytes(filepath)
            except Exception as exc:
                log.warning(f"[Player] Error al reproducir {filepath.name}: {exc}")
                return False
        self._fire_state_change()
        return True

    def seek(self, seconds: float) -> bool:
        """Jump to *seconds* into the current track."""
        if self._current is None:
            return False
        return self.play(self._current, start=seconds)

    def set_volume(self, value: float) -> None:
        """Set output volume (0.0 - 1.0)."""
        value = max(0.0, min(1.0, value))
        self._volume = value
        if self._ready:
            try:
                import pygame
                pygame.mixer.music.set_volume(value)
            except Exception:
                pass
        self._fire_state_change()

    def get_position(self) -> float:
        """Return current playback position in seconds (best effort).

        pygame returns ms since the *last* play() call, so we add the seek
        offset baked in during the last play(start=...) call.
        """
        if not self._ready or self._current is None:
            return 0.0
        try:
            import pygame
            ms = pygame.mixer.music.get_pos()
            if ms < 0:
                return self._start_pos
            return self._start_pos + (ms / 1000.0)
        except Exception:
            return 0.0

    @property
    def volume(self) -> float:
        return self._volume

    @property
    def duration(self) -> float:
        return self._duration

    def stop(self) -> None:
        """Stop playback completely."""
        with self._lock:
            if not self._ready:
                return
            try:
                import pygame
                pygame.mixer.music.stop()
            except Exception:
                pass
            self._current = None
            self._paused  = False
        self._fire_state_change()

    def toggle_pause(self) -> bool:
        """
        Pause if playing, resume if paused.

        Returns:
            ``True`` if now paused, ``False`` if now playing (or nothing
            playing).
        """
        with self._lock:
            if not self._ready or self._current is None:
                return False
            try:
                import pygame
                if self._paused:
                    pygame.mixer.music.unpause()
                    self._paused = False
                else:
                    pygame.mixer.music.pause()
                    self._paused = True
            except Exception:
                pass
            paused = self._paused
        self._fire_state_change()
        return paused

    def is_playing(self, filepath: Optional[Path] = None) -> bool:
        """
        True when *filepath* (or any file, if omitted) is currently the
        active track and the mixer is producing audio.
        """
        with self._lock:
            if not self._ready or self._current is None:
                return False
            if filepath is not None:
                try:
                    if Path(filepath).resolve() != self._current.resolve():
                        return False
                except Exception:
                    return False
            try:
                import pygame
                return bool(pygame.mixer.music.get_busy()) and not self._paused
            except Exception:
                return False

    @property
    def current(self) -> Optional[Path]:
        return self._current

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def title(self) -> str:
        return self._title

    @property
    def artist(self) -> str:
        return self._artist

    @property
    def cover_bytes(self) -> Optional[bytes]:
        return self._cover_bytes

    # ── Queue / next / prev ─────────────────────────────────────────────────

    def set_queue(self, paths: list[Path], current: Path) -> None:
        """Replace the queue.  The current track is whichever entry equals
        *current*; if missing, the queue is set but next/prev are no-ops."""
        self._queue = [Path(p) for p in paths]
        try:
            self._queue_idx = next(
                i for i, p in enumerate(self._queue)
                if p.resolve() == Path(current).resolve()
            )
        except StopIteration:
            self._queue_idx = -1

    def next(self) -> bool:
        if not self._queue or self._queue_idx < 0:
            return False
        for i in range(self._queue_idx + 1, len(self._queue)):
            if self._queue[i].exists():
                self._queue_idx = i
                return self.play(self._queue[i])
        return False

    def prev(self) -> bool:
        if not self._queue or self._queue_idx < 0:
            return False
        for i in range(self._queue_idx - 1, -1, -1):
            if self._queue[i].exists():
                self._queue_idx = i
                return self.play(self._queue[i])
        return False

    @property
    def has_next(self) -> bool:
        if not self._queue or self._queue_idx < 0:
            return False
        return any(self._queue[i].exists()
                   for i in range(self._queue_idx + 1, len(self._queue)))

    @property
    def has_prev(self) -> bool:
        if not self._queue or self._queue_idx < 0:
            return False
        return any(self._queue[i].exists()
                   for i in range(0, self._queue_idx))

    # ── Observers ────────────────────────────────────────────────────────────

    def subscribe(self, callback: Callable) -> None:
        """Register a callback to fire on every play/stop/pause."""
        self._on_state_change.append(callback)

    def _fire_state_change(self) -> None:
        for cb in list(self._on_state_change):
            try:
                cb()
            except Exception:
                pass
