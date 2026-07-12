"""
utils/ytdlp_updater.py
========================
Self-contained yt-dlp update helper.

Extracted from ``core.controller`` (was 89 lines nested inside
``AppController.update_ytdlp``) — the function doesn't touch controller
state, so it belongs in utils/.  Living here also makes it directly
testable without spinning up an entire AppController + SearchManager
+ HistoryManager stack.

YouTube changes its bot protection every few months and yt-dlp ships
fixes very fast — keeping it fresh is the single best remedy for the
"HTTP 403 / video unavailable" downloader class of errors.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys

log = logging.getLogger("dj_tracks.ytdlp_updater")


def _norm(v: str) -> tuple:
    """Normalise a version string for comparison.

    PyPI reports ``2026.6.9`` while yt-dlp's ``__version__`` is
    ``2026.06.09`` — same release, different formatting.  Cast every
    numeric component to int so the tuple compares on the actual
    numbers rather than string ordering.
    """
    parts = []
    for p in v.replace("-", ".").split("."):
        try:
            parts.append(int(p))
        except ValueError:
            parts.append(p)
    return tuple(parts)


def update_ytdlp() -> dict[str, str]:
    """Check PyPI for a newer yt-dlp release; install it if available.

    Runs the upgrade in a **separate detached Python process** so it can
    finish safely even if the user quits DJ Tracks — replacing yt-dlp
    files while the module is loaded in-process would corrupt the
    interpreter on Windows (locked .pyd files).

    Returns:
        Dict with keys:

        - ``status``  — ``"up-to-date"`` | ``"updated"`` | ``"error"``
        - ``current`` — installed version (``"?"`` if yt-dlp is broken)
        - ``latest``  — PyPI version when known, else ``"?"``
        - ``message`` — human-friendly Spanish text for the UI
    """
    # Current version.
    try:
        import yt_dlp
        current = yt_dlp.version.__version__
    except Exception as exc:
        return {
            "status":  "error",
            "current": "?",
            "latest":  "?",
            "message": f"yt-dlp no se pudo cargar: {exc}",
        }

    # Latest version on PyPI.
    try:
        import requests
        r = requests.get("https://pypi.org/pypi/yt-dlp/json", timeout=8)
        r.raise_for_status()
        latest = r.json().get("info", {}).get("version", "?")
    except Exception as exc:
        log.warning(f"[ytdlp_updater] PyPI unreachable: {exc}")
        return {
            "status":  "error",
            "current": current,
            "latest":  "?",
            "message": f"No se pudo consultar PyPI: {exc}",
        }

    if _norm(current) == _norm(latest):
        return {
            "status":  "up-to-date",
            "current": current,
            "latest":  latest,
            "message": f"yt-dlp ya está actualizado (v{current})",
        }

    # Detached subprocess.  CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS
    # on Windows so the child outlives us cleanly; start_new_session
    # is the POSIX equivalent.
    try:
        kwargs: dict = {}
        if os.name == "nt":
            kwargs["creationflags"] = (
                subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                | 0x00000008                         # DETACHED_PROCESS
            )
        else:
            kwargs["start_new_session"] = True

        subprocess.Popen(
            [sys.executable, "-m", "pip", "install", "--upgrade",
             "--quiet", "--disable-pip-version-check", "yt-dlp"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            **kwargs,
        )
    except Exception as exc:
        return {
            "status":  "error",
            "current": current,
            "latest":  latest,
            "message": f"No se pudo lanzar el instalador: {exc}",
        }

    log.info(f"[ytdlp_updater] upgrade lanzado en segundo plano: "
             f"{current} → {latest}")
    return {
        "status":  "updated",
        "current": current,
        "latest":  latest,
        "message": (f"Actualizando yt-dlp en segundo plano "
                    f"(v{current} → v{latest}).\n\n"
                    f"Cierra y vuelve a abrir DJ Tracks dentro de "
                    f"30 segundos para usar la nueva versión."),
    }
