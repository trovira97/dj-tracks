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

    def play(self, filepath: Path) -> bool:
        """
        Play *filepath*.  If something else is playing, it's replaced.

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
                pygame.mixer.music.play()
                self._current = filepath
                self._paused  = False
            except Exception as exc:
                log.warning(f"[Player] Error al reproducir {filepath.name}: {exc}")
                return False
        self._fire_state_change()
        return True

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
