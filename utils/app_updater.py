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

import json
import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
from pathlib import Path
from typing import Callable, Optional

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


def _pick_asset(assets: list) -> Optional[dict]:
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
                     repo: Optional[str] = None,
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
                   progress: Optional[Callable[[int, int], None]] = None,
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
                        try:
                            progress(done, total)
                        except Exception:
                            pass
        return True
    except Exception as exc:
        log.error(f"[Updater] download failed: {exc}")
        try:
            dest_path.unlink(missing_ok=True)
        except Exception:
            pass
        return False


# ── Apply ──────────────────────────────────────────────────────────────────

def is_frozen() -> bool:
    """True when running from a PyInstaller bundle."""
    return getattr(sys, "frozen", False)


def apply_update(new_exe_path: Path) -> bool:
    """Swap the running executable for *new_exe_path* and re-launch.

    Only supported on Windows + frozen builds.  This call terminates
    the current process on success (sys.exit), so anything important
    must be persisted BEFORE calling.
    """
    if not is_frozen():
        log.error("[Updater] apply_update called from non-frozen run — aborting")
        return False
    if not sys.platform.startswith("win"):
        log.error("[Updater] apply_update only supports Windows for now")
        return False

    current = Path(sys.executable).resolve()
    new_exe = Path(new_exe_path).resolve()
    if not new_exe.exists():
        log.error(f"[Updater] new exe missing: {new_exe}")
        return False

    # Stash the running .exe under a .old name (Windows allows rename
    # of a running binary, just not delete).
    backup = current.with_suffix(current.suffix + ".old")
    try:
        if backup.exists():
            backup.unlink()
        os.rename(current, backup)
    except Exception as exc:
        log.error(f"[Updater] could not rename current exe: {exc}")
        return False

    # Drop the new binary in place.
    try:
        shutil.copy2(new_exe, current)
    except Exception as exc:
        log.error(f"[Updater] copy failed, rolling back: {exc}")
        try:
            os.rename(backup, current)
        except Exception:
            pass
        return False

    # Write a .bat that waits for THIS process to exit, deletes the
    # backup, launches the new exe, and self-deletes.
    pid = os.getpid()
    bat = Path(tempfile.gettempdir()) / f"dj_tracks_update_{pid}.bat"
    bat_body = (
        '@echo off\r\n'
        'setlocal\r\n'
        f':wait\r\n'
        f'tasklist /FI "PID eq {pid}" | find "{pid}" >nul\r\n'
        'if not errorlevel 1 ( timeout /t 1 /nobreak >nul & goto wait )\r\n'
        f'del /F /Q "{backup}" >nul 2>&1\r\n'
        f'start "" "{current}"\r\n'
        f'del /F /Q "{bat}" >nul 2>&1\r\n'
    )
    try:
        bat.write_text(bat_body, encoding="ascii")
    except Exception as exc:
        log.error(f"[Updater] could not write relaunch script: {exc}")
        return False

    DETACHED_PROCESS = 0x00000008
    CREATE_NEW_PROCESS_GROUP = 0x00000200
    try:
        subprocess.Popen(
            ["cmd", "/c", str(bat)],
            creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP,
            close_fds=True,
        )
    except Exception as exc:
        log.error(f"[Updater] could not launch relaunch script: {exc}")
        return False

    log.info("[Updater] update staged — exiting for relaunch")
    # Tell the GUI to close cleanly if it's listening, then bail.
    threading.Thread(target=lambda: os._exit(0), daemon=False).start()
    return True
