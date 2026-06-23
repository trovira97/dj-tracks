"""
utils/paths.py
===============
Central resolver for runtime data paths.

When the app is **frozen** (running from a PyInstaller bundle), the
on-disk project layout is read-only (e.g. installed under
``C:\\Program Files`` or ``%LOCALAPPDATA%\\DJ Tracks``), so writable
data must live elsewhere.  This module returns the right directory in
every case:

============= ============================================
Mode          Data directory
============= ============================================
Source        ``<repo>/config``,  ``<repo>/logs``
Frozen .exe   ``%APPDATA%/DjTracks/...`` (per-user)
============= ============================================

The frozen detection is the standard PyInstaller idiom
(``sys.frozen`` attribute injected at runtime by the bootloader).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_APP_NAME    = "DjTracks"
_APP_AUTHOR  = "DjTracks"
_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def is_frozen() -> bool:
    """Return True if running inside a PyInstaller-built executable."""
    return getattr(sys, "frozen", False)


def user_data_dir() -> Path:
    """
    Root directory for user-writable data (config, logs, history, queue).

    - Source mode: ``<project>/`` (legacy layout — kept so dev workflows
      and existing user data stay where they are).
    - Frozen mode: platform-appropriate user data dir (uses ``platformdirs``
      when available, falls back to ``%APPDATA%`` / ``~/.local/share``).
    """
    if not is_frozen():
        return _PROJECT_ROOT

    try:
        from platformdirs import user_data_dir as _udd
        base = Path(_udd(_APP_NAME, _APP_AUTHOR, roaming=True))
    except Exception:
        # Manual fallback for environments where platformdirs isn't bundled.
        if os.name == "nt":
            base = Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / _APP_NAME
        else:
            base = Path.home() / ".local/share" / _APP_NAME
    base.mkdir(parents=True, exist_ok=True)
    return base


def config_dir() -> Path:
    """Directory for ``settings.json``, ``history.json``, ``queue.json``."""
    d = user_data_dir() / "config"
    d.mkdir(parents=True, exist_ok=True)
    return d


def logs_dir() -> Path:
    """Directory for application log files."""
    d = user_data_dir() / "logs"
    d.mkdir(parents=True, exist_ok=True)
    return d


def bundled_resource(relative: str) -> Path:
    """
    Resolve a read-only bundled resource path (assets, ffmpeg, etc.).

    PyInstaller extracts the bundle to ``sys._MEIPASS`` at startup;
    in source mode resources live next to the project root.
    """
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS) / relative
    return _PROJECT_ROOT / relative
