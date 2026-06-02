"""
main.py
========
DJ Tracks — Music Downloader  ·  Entry point.

Bootstraps optional dependencies, then launches the GUI.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

# ─────────────────────────────────────────────────────────────────────────────
# Python version guard  (requires 3.9+ for dict[...] syntax in dependencies)
# ─────────────────────────────────────────────────────────────────────────────
if sys.version_info < (3, 9):
    print(
        f"[DJ Tracks] ERROR: Python 3.9+ requerido — detectado {sys.version}\n"
        "Por favor lanza la app desde iniciar.bat o instala Python 3.10+.",
        file=sys.stderr,
    )
    sys.exit(1)

# ─────────────────────────────────────────────────────────────────────────────
# sys.path setup
# ─────────────────────────────────────────────────────────────────────────────

ROOT   = Path(__file__).parent
VENDOR = ROOT / ".vendor"

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if VENDOR.exists() and str(VENDOR) not in sys.path:
    sys.path.insert(0, str(VENDOR))


# ─────────────────────────────────────────────────────────────────────────────
# Dependency bootstrap
# ─────────────────────────────────────────────────────────────────────────────

def _pip_install(*packages: str, quiet: bool = True) -> bool:
    """
    Install *packages* via the current interpreter's pip.

    Returns ``True`` if pip exited with code 0.
    """
    cmd = [sys.executable, "-m", "pip", "install", *packages]
    if quiet:
        cmd.append("--quiet")
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        print(f"[DJ Tracks] pip error: {(result.stderr or result.stdout).strip()}", file=sys.stderr)
    return result.returncode == 0


def _can_import(name: str) -> bool:
    """Return ``True`` if *name* can be imported without raising ImportError."""
    import importlib
    try:
        importlib.import_module(name)
        return True
    except ImportError:
        return False


def _bootstrap() -> None:
    """
    Auto-install any missing runtime dependencies.

    Keeps distribution simple: users only need Python + this project;
    they do not need to run ``pip install -r requirements.txt`` manually.
    """
    # (import_name, pip_package_name)
    core_deps = [
        ("customtkinter", "customtkinter"),
        ("PIL",           "Pillow"),
        ("yt_dlp",        "yt-dlp"),
        ("spotipy",       "spotipy"),
        ("mutagen",       "mutagen"),
        ("slugify",       "python-slugify"),
        ("requests",      "requests"),
        ("platformdirs",  "platformdirs"),
        ("tkinterdnd2",   "tkinterdnd2"),   # optional drag-and-drop
        ("qrcode",        "qrcode[pil]"),   # optional donation QR codes
    ]

    missing = [pkg for imp, pkg in core_deps if not _can_import(imp)]
    if missing:
        print(f"[DJ Tracks] Instalando dependencias faltantes: {', '.join(missing)}")
        if not _pip_install(*missing):
            print("[DJ Tracks] Advertencia: algunas dependencias no se pudieron instalar.",
                  file=sys.stderr)

    # spotdl — try latest first, fall back to last known-good version.
    if not _can_import("spotdl"):
        print("[DJ Tracks] Instalando spotdl…")
        if not _pip_install("spotdl"):
            print("[DJ Tracks] Intentando spotdl==4.2.11…")
            _pip_install("spotdl==4.2.11")

    # soundcloud-v2 — pip name differs from import name.
    if not _can_import("soundcloud"):
        _pip_install("soundcloud-v2")


# ─────────────────────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    """Initialise the controller and start the GUI main loop."""
    # ── 1) Windows-native polish (no-ops elsewhere) ──────────────────────────
    # Must run BEFORE any module imports yt-dlp / asyncio / subprocess use.
    from utils.win_native import install_all as _install_win_polish
    _install_win_polish()

    # ── 2) Bootstrap deps (only in source mode) ──────────────────────────────
    if not getattr(sys, "frozen", False):
        _bootstrap()

    # ── 3) Single-instance lock — refuse to launch a duplicate ───────────────
    from utils.single_instance import acquire as _acquire_single, release as _release_single
    if not _acquire_single():
        try:
            import tkinter as _tk
            from tkinter import messagebox as _mb
            _root = _tk.Tk()
            _root.withdraw()
            _mb.showinfo("DJ Tracks",
                         "DJ Tracks ya se está ejecutando.\nRevisa la barra de tareas.")
            _root.destroy()
        except Exception:
            print("DJ Tracks ya se está ejecutando.", file=sys.stderr)
        return

    try:
        from core.controller import AppController
        from ui.gui          import DjTracksDwCrackApp

        controller = AppController()
        app        = DjTracksDwCrackApp(controller)
        app.run()
    finally:
        _release_single()


if __name__ == "__main__":
    main()
