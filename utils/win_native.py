"""
utils/win_native.py
====================
Windows-native polish: subprocess console suppression, AppUserModelID,
and asyncio event-loop policy.

These tweaks make the app feel native on Windows:

- **Subprocess patch**: any child process the app launches (yt-dlp,
  ffmpeg, helper PowerShell calls, etc.) starts without a flashing
  CMD window.
- **AppUserModelID**: tells Explorer to group / icon the app under
  its own identity instead of bundling it with all "python.exe"
  processes — the taskbar shows the DJ Tracks icon.
- **Asyncio policy**: ``WindowsSelectorEventLoopPolicy`` avoids
  ``RuntimeError: Event loop is closed`` shutdown noise when third
  parties (yt-dlp) close their own loops on exit.

All of these are no-ops on non-Windows platforms.
"""
from __future__ import annotations

import asyncio
import subprocess
import sys

_AUMID = "DjTracks.MusicDownloader"


def install_silent_subprocess() -> None:
    """
    Monkey-patch ``subprocess.Popen`` so every child process spawned by
    the app (directly or indirectly) starts with ``CREATE_NO_WINDOW``
    and ``SW_HIDE`` on Windows.  Idempotent — safe to call once at boot.
    """
    if sys.platform != "win32":
        return
    if getattr(subprocess.Popen, "_dj_silent_patched", False):
        return

    _CREATE_NO_WINDOW   = 0x08000000
    _CREATE_NEW_CONSOLE = 0x00000010
    _orig_init          = subprocess.Popen.__init__

    def _silent_init(self, args, **kwargs):
        cf = kwargs.get("creationflags", 0) & ~_CREATE_NEW_CONSOLE
        cf |= _CREATE_NO_WINDOW
        kwargs["creationflags"] = cf
        if "startupinfo" not in kwargs:
            si = subprocess.STARTUPINFO()
            si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
            si.wShowWindow = 0  # SW_HIDE
            kwargs["startupinfo"] = si
        _orig_init(self, args, **kwargs)

    _silent_init._dj_silent_patched = True   # type: ignore[attr-defined]
    subprocess.Popen.__init__ = _silent_init
    subprocess.Popen._dj_silent_patched = True   # type: ignore[attr-defined]


def set_app_user_model_id(aumid: str = _AUMID) -> None:
    """
    Register a custom Application User Model ID so Windows shows the
    app's own icon in the taskbar instead of the generic Python icon.
    """
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(aumid)
    except Exception:
        pass


def install_asyncio_policy() -> None:
    """
    Use the selector event loop on Windows.  The proactor loop (default
    on 3.8+) is faster for sockets but produces shutdown errors when
    used with libraries that close it independently (yt-dlp does this).
    """
    if sys.platform != "win32":
        return
    try:
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    except Exception:
        pass


def install_all() -> None:
    """Convenience: apply every Windows polish in one call."""
    install_silent_subprocess()
    install_asyncio_policy()
    set_app_user_model_id()
