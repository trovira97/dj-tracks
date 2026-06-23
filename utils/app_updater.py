"""
utils/app_updater.py
=====================
In-app updater backed by GitHub Releases.

Flow:
  1. ``check_for_update(current_version)`` queries
     ``api.github.com/repos/{REPO}/releases/latest`` (no auth — 60
     req/h per IP is plenty).  Returns a dict describing the latest
     release and whether it's newer than what's running.
  2. ``download_asset(...)`` streams the chosen asset to a temp file.
  3. ``apply_update(...)`` swaps the running executable for the new
     one and re-launches the app.  Windows-specific: a tiny .bat
     waits for the current process to exit, deletes the old binary
     and starts the new one.

When running from source (not a PyInstaller build) the updater
refuses to apply — it only knows how to swap a frozen ``.exe``.
"""
from __future__ import annotations

import contextlib
import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger("dj_tracks.updater")

# Default repo — overridden by settings.json["github_repo"].
DEFAULT_REPO = "trovira97/dj-tracks"


# ── Version parsing ─────────────────────────────────────────────────────────

_VER_RE = re.compile(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[\.-](\d+))?")


def _parse_version(s: str) -> tuple:
    """'v2.1.0' / '2.1' / '2.1.0-rc1' → comparable tuple of ints."""
    if not s:
        return (0,)
    m = _VER_RE.search(s.strip().lstrip("vV"))
    if not m:
        return (0,)
    return tuple(int(x) if x else 0 for x in m.groups())


def is_newer(remote: str, local: str) -> bool:
    return _parse_version(remote) > _parse_version(local)


# ── GitHub release lookup ──────────────────────────────────────────────────

def _settings_path() -> Path:
    try:
        from utils.paths import config_dir
        return config_dir() / "settings.json"
    except Exception:
        return Path("config/settings.json")


def _repo() -> str:
    """Resolve the GitHub repo from settings, falling back to default."""
    try:
        p = _settings_path()
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            r = (data.get("github_repo") or "").strip()
            if r:
                return r
    except Exception:
        pass
    return DEFAULT_REPO


def _pick_asset(assets: list) -> dict | None:
    """Pick the right asset for the current platform.

    Preference order: .exe (Windows installer/portable) → .zip with
    'win' in the name → first asset.  Anyone running on macOS / Linux
    falls back to whatever's there (rare — the app is Windows-first).
    """
    if not assets:
        return None
    if sys.platform.startswith("win"):
        exes = [a for a in assets if a["name"].lower().endswith(".exe")]
        if exes:
            return exes[0]
        zips = [a for a in assets
                if a["name"].lower().endswith(".zip")
                and "win" in a["name"].lower()]
        if zips:
            return zips[0]
    return assets[0]


def check_for_update(current_version: str,
                     repo: str | None = None,
                     timeout: float = 8.0) -> dict:
    """Return ``{available, latest, url, asset_url, asset_name,
    asset_size, body, repo}``.  ``available`` is False on any error so
    the UI can stay quiet.
    """
    repo = repo or _repo()
    url  = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        import requests
        r = requests.get(url, timeout=timeout,
                         headers={"Accept": "application/vnd.github+json",
                                  "User-Agent": "dj-tracks-updater"})
        if r.status_code != 200:
            log.info(f"[Updater] GitHub HTTP {r.status_code} for {url}")
            return {"available": False, "repo": repo}
        rel = r.json()
    except Exception as exc:
        log.info(f"[Updater] check failed: {exc}")
        return {"available": False, "repo": repo}

    latest = rel.get("tag_name") or ""
    asset  = _pick_asset(rel.get("assets") or [])
    avail  = bool(latest) and is_newer(latest, current_version)

    return {
        "available":  avail,
        "latest":     latest,
        "url":        rel.get("html_url", ""),
        "asset_url":  (asset or {}).get("browser_download_url", ""),
        "asset_name": (asset or {}).get("name", ""),
        "asset_size": (asset or {}).get("size", 0),
        "body":       rel.get("body", "")[:600],
        "repo":       repo,
    }


# ── Download with progress ─────────────────────────────────────────────────

def download_asset(asset_url: str, dest_path: Path,
                   progress: Callable[[int, int], None] | None = None,
                   chunk_size: int = 64 * 1024) -> bool:
    """Stream *asset_url* to *dest_path*.  Calls progress(done, total)
    every chunk.  Returns True on success."""
    try:
        import requests
        with requests.get(asset_url, stream=True, timeout=30,
                          headers={"User-Agent": "dj-tracks-updater"}) as r:
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or 0)
            done  = 0
            with open(dest_path, "wb") as fh:
                for chunk in r.iter_content(chunk_size=chunk_size):
                    if not chunk:
                        continue
                    fh.write(chunk)
                    done += len(chunk)
                    if progress:
                        with contextlib.suppress(Exception):
                            progress(done, total)
        return True
    except Exception as exc:
        log.error(f"[Updater] download failed: {exc}")
        with contextlib.suppress(Exception):
            dest_path.unlink(missing_ok=True)
        return False


# ── Apply ──────────────────────────────────────────────────────────────────

def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def _spawn_relaunch_bat(commands: list[str], exe_to_launch: Path) -> bool:
    """Write + spawn a detached .bat that:
       1. waits for the current PID to die
       2. runs each line in *commands* (robocopy / move / rmdir / del…)
       3. launches *exe_to_launch*
       4. deletes itself
    Returns True if Popen succeeded.
    """
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / f"dj_tracks_update_{pid}.bat"
    lines = ['@echo off', 'setlocal',
             ':wait',
             f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul',
             'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto wait )']
    lines.extend(commands)
    lines.append(f'start "" "{exe_to_launch}"')
    lines.append(f'del /F /Q "{bat}" >nul 2>&1')
    try:
        bat.write_text("\r\n".join(lines) + "\r\n", encoding="ascii")
    except Exception as exc:
        log.error(f"[Updater] could not write relaunch script: {exc}")
        return False

    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    try:
        subprocess.Popen(["cmd", "/c", str(bat)],
                         creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
                         close_fds=True)
    except Exception as exc:
        log.error(f"[Updater] could not launch relaunch script: {exc}")
        return False
    return True


def _apply_exe_swap(current_exe: Path, new_exe: Path) -> bool:
    """Single-file mode: rename current .exe to .old, copy new in place,
    relaunch via .bat that deletes the backup."""
    backup = current_exe.with_suffix(current_exe.suffix + ".old")
    try:
        if backup.exists():
            backup.unlink()
        os.rename(current_exe, backup)
    except Exception as exc:
        log.error(f"[Updater] could not rename current exe: {exc}")
        return False
    try:
        shutil.copy2(new_exe, current_exe)
    except Exception as exc:
        log.error(f"[Updater] copy failed, rolling back: {exc}")
        with contextlib.suppress(Exception):
            os.rename(backup, current_exe)
        return False
    commands = [f'del /F /Q "{backup}" >nul 2>&1']
    return _spawn_relaunch_bat(commands, current_exe)


def _apply_zip_swap(current_exe: Path, zip_path: Path) -> bool:
    """Folder-bundle mode (PyInstaller --onedir): extract the .zip,
    locate the install folder inside, and schedule a .bat that
    replaces the whole install directory once we're gone.

    Layout assumed:
        <install_dir>/DJ Tracks.exe   <- sys.executable
        <install_dir>/_internal/...
    The .zip is assumed to contain a top-level folder that holds the
    new .exe plus its _internal/.
    """
    import zipfile

    install_dir = current_exe.parent
    parent_dir  = install_dir.parent
    exe_name    = current_exe.name

    # Extract to a sibling staging folder so robocopy can move it.
    staging = parent_dir / f".{install_dir.name}.update"
    if staging.exists():
        shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(staging)
    except Exception as exc:
        log.error(f"[Updater] zip extraction failed: {exc}")
        shutil.rmtree(staging, ignore_errors=True)
        return False

    # Find the folder inside the zip that contains a copy of our .exe.
    new_root: Path | None = None
    # Most common: zip wraps a single folder.
    for candidate in [staging, *staging.iterdir()]:
        if candidate.is_dir() and (candidate / exe_name).exists():
            new_root = candidate
            break
    if new_root is None:
        # Fallback: walk to find the exe.
        for path in staging.rglob(exe_name):
            new_root = path.parent
            break
    if new_root is None or not new_root.exists():
        log.error(f"[Updater] new {exe_name} not found inside zip")
        shutil.rmtree(staging, ignore_errors=True)
        return False

    # Schedule the install swap.  We use robocopy /MIR (mirror) which
    # is the standard Windows trick for replacing a directory tree
    # whose top-level folder cannot be deleted while we're using it.
    new_exe_after = install_dir / exe_name
    commands = [
        # robocopy returns 0-7 on success; suppress its non-zero exit.
        f'robocopy "{new_root}" "{install_dir}" /MIR /R:2 /W:2 /NFL /NDL /NJH /NJS /NP >nul 2>&1',
        f'rmdir /S /Q "{staging}" >nul 2>&1',
    ]
    return _spawn_relaunch_bat(commands, new_exe_after)


def apply_update(new_asset_path: Path) -> bool:
    """Apply a downloaded update and re-launch.  *new_asset_path* may
    be a single .exe (PyInstaller --onefile) or a .zip containing the
    install folder (--onedir).  Detects which and dispatches.

    Only supported on Windows + frozen builds.  Terminates the current
    process on success — anything important must be persisted before
    calling.
    """
    if not is_frozen():
        log.error("[Updater] apply_update called from non-frozen run — aborting")
        return False
    if not sys.platform.startswith("win"):
        log.error("[Updater] apply_update only supports Windows for now")
        return False

    current = Path(sys.executable).resolve()
    new     = Path(new_asset_path).resolve()
    if not new.exists():
        log.error(f"[Updater] downloaded asset missing: {new}")
        return False

    suffix = new.suffix.lower()
    if suffix == ".exe":
        ok = _apply_exe_swap(current, new)
    elif suffix == ".zip":
        ok = _apply_zip_swap(current, new)
    else:
        log.error(f"[Updater] unsupported asset type: {suffix}")
        return False

    if not ok:
        return False

    log.info("[Updater] update staged — exiting for relaunch")
    threading.Thread(target=lambda: os._exit(0), daemon=False).start()
    return True
