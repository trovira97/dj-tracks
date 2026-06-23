"""
utils/shortcut.py
==================
Create a desktop launcher for DJ Tracks on any major platform.

- **Windows**: ``.lnk`` via PowerShell + WScript.Shell.
- **macOS**:   ``.command`` shell script (chmod +x).
- **Linux**:   ``.desktop`` file (XDG).

Each function returns the path of the created shortcut on success,
or raises ``RuntimeError`` with a human-friendly message.
"""
from __future__ import annotations

import contextlib
import os
import subprocess
import sys
from pathlib import Path


def _project_root() -> Path:
    """Source-checkout root or frozen-bundle directory."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parent.parent


def _icon_path() -> Path | None:
    p = _project_root() / "assets" / "icon.ico"
    return p if p.exists() else None


def _logo_path() -> Path | None:
    p = _project_root() / "assets" / "logo.png"
    return p if p.exists() else None


# ─────────────────────────────────────────────────────────────────────────────
# Windows
# ─────────────────────────────────────────────────────────────────────────────

def _windows_desktop() -> Path:
    """Return the actual Desktop directory (handles locales + OneDrive)."""
    try:
        import winreg
        with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders") as k:
            path, _ = winreg.QueryValueEx(k, "Desktop")
            if path and Path(path).is_dir():
                return Path(path)
    except Exception:
        pass
    return Path.home() / "Desktop"


def _create_windows() -> Path:
    root    = _project_root()
    icon    = _icon_path()
    icon_s  = str(icon) if icon else ""

    if getattr(sys, "frozen", False):
        target_exe = sys.executable
        arguments  = ""
    else:
        # Prefer pythonw.exe so no console window flashes when launching.
        py_dir   = Path(sys.executable).parent
        pythonw  = py_dir / "pythonw.exe"
        target_exe = str(pythonw if pythonw.exists() else sys.executable)
        script     = root / "main.py"
        arguments  = f'"{script}"'

    desktop = _windows_desktop()
    target  = desktop / "DJ Tracks.lnk"

    ps = (
        f'$s=(New-Object -COM WScript.Shell).CreateShortcut("{target}");'
        f'$s.TargetPath="{target_exe}";'
        f'$s.Arguments="{arguments}";'
        f'$s.WorkingDirectory="{root}";'
        f'$s.IconLocation="{icon_s}";'
        f'$s.Description="DJ Tracks Music Downloader";'
        f'$s.WindowStyle=1;'
        f'$s.Save()'
    )
    result = subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
        capture_output=True, text=True, timeout=15,
    )
    if not target.exists():
        raise RuntimeError(
            f"PowerShell no creó el acceso directo: {result.stderr.strip() or 'desconocido'}"
        )
    return target


# ─────────────────────────────────────────────────────────────────────────────
# macOS
# ─────────────────────────────────────────────────────────────────────────────

def _create_macos() -> Path:
    root    = _project_root()
    desktop = Path.home() / "Desktop"
    desktop.mkdir(exist_ok=True)
    target  = desktop / "DJ Tracks.command"

    if getattr(sys, "frozen", False):
        contents = f'#!/bin/bash\ncd "{root}"\n"{sys.executable}"\n'
    else:
        contents = (
            f'#!/bin/bash\n'
            f'cd "{root}"\n'
            f'"{sys.executable}" main.py\n'
        )
    target.write_text(contents, encoding="utf-8")
    os.chmod(target, 0o755)
    return target


# ─────────────────────────────────────────────────────────────────────────────
# Linux
# ─────────────────────────────────────────────────────────────────────────────

def _linux_desktop() -> Path | None:
    home = Path.home()
    # Try XDG user-dirs.dirs first (locale-aware).
    user_dirs = home / ".config" / "user-dirs.dirs"
    if user_dirs.is_file():
        try:
            for line in user_dirs.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if line.startswith("XDG_DESKTOP_DIR="):
                    val = line.split("=", 1)[1].strip().strip('"').replace("$HOME", str(home))
                    p = Path(val)
                    if p.is_dir():
                        return p
        except Exception:
            pass
    for name in ("Desktop", "Escritorio", "Bureau", "Schreibtisch",
                 "Рабочий стол", "桌面", "바탕화면", "デスクトップ"):
        p = home / name
        if p.is_dir():
            return p
    return None


def _create_linux() -> Path:
    root  = _project_root()
    icon  = _logo_path() or _icon_path()
    desktop = _linux_desktop()

    if getattr(sys, "frozen", False):
        exec_line = str(Path(sys.executable))
    else:
        exec_line = f'{sys.executable} {root / "main.py"}'

    contents = (
        "[Desktop Entry]\n"
        "Name=DJ Tracks\n"
        "Comment=DJ Tracks Music Downloader\n"
        f"Exec={exec_line}\n"
        f"Icon={icon}\n"
        "Terminal=false\n"
        "Type=Application\n"
        "Categories=Music;AudioVideo;\n"
        "StartupWMClass=DJ Tracks\n"
    )

    if desktop:
        target = desktop / "DJ Tracks.desktop"
    else:
        apps_dir = Path.home() / ".local" / "share" / "applications"
        apps_dir.mkdir(parents=True, exist_ok=True)
        target = apps_dir / "DJ Tracks.desktop"

    target.write_text(contents, encoding="utf-8")
    os.chmod(target, 0o755)

    # Mark as trusted on GNOME (silent best-effort).
    with contextlib.suppress(Exception):
        subprocess.run(["gio", "set", str(target), "metadata::trusted", "true"],
                       capture_output=True, timeout=5)
    return target


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def create_shortcut() -> Path:
    """
    Create a desktop launcher for the current platform.

    Returns:
        Path of the created shortcut.

    Raises:
        RuntimeError: on platform-specific failure.
    """
    if sys.platform == "win32":
        return _create_windows()
    if sys.platform == "darwin":
        return _create_macos()
    return _create_linux()
