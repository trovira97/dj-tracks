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
                self._duration  = _read_duration(filepath)
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
