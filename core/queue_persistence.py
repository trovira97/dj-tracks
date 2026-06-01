"""
core/queue_persistence.py
==========================
Persist pending download tasks across app restarts.

Only tasks in non-terminal states (PENDING / DOWNLOADING / SEARCHING /
PROCESSING) are saved.  Active downloads are demoted to PENDING on reload
so the worker pool picks them up again from scratch.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import List, Optional

from downloader.audio_downloader import DownloadStatus, DownloadTask
from downloader.quality_manager  import get_profile
from providers                   import TrackInfo
from utils.logger                import log


QUEUE_PATH = Path(__file__).parent.parent / "config" / "queue.json"

_TERMINAL = {DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED}


def _task_to_dict(task: DownloadTask) -> dict:
    """Serialise a :class:`DownloadTask` to a plain dict."""
    t = task.track
    return {
        "track": {
            "title":       t.title,
            "artists":     t.artists,
            "album":       t.album,
            "year":        t.year,
            "genre":       t.genre,
            "duration_ms": t.duration_ms,
            "isrc":        t.isrc,
            "cover_url":   t.cover_url,
            "source_url":  t.source_url,
            "platform":    t.platform,
            "track_id":    t.track_id,
        },
        "profile_format":  task.profile.format.value,
        "profile_quality": task.profile.quality.value,
        "output_dir":      task.output_dir,
        "structure":       task.structure,
    }


def _dict_to_task(d: dict) -> Optional[DownloadTask]:
    """Reconstruct a :class:`DownloadTask` from a dict.  Returns None on failure."""
    try:
        tr = d.get("track") or {}
        track = TrackInfo(
            title       = tr.get("title", "Unknown"),
            artists     = tr.get("artists", ["Unknown"]),
            album       = tr.get("album", ""),
            year        = tr.get("year", ""),
            genre       = tr.get("genre", ""),
            duration_ms = tr.get("duration_ms", 0),
            isrc        = tr.get("isrc", ""),
            cover_url   = tr.get("cover_url", ""),
            source_url  = tr.get("source_url", ""),
            platform    = tr.get("platform", ""),
            track_id    = tr.get("track_id", ""),
        )
        profile = get_profile(
            d.get("profile_format", "mp3"),
            d.get("profile_quality", "320k"),
        )
        return DownloadTask(
            track      = track,
            profile    = profile,
            output_dir = d.get("output_dir", "downloads"),
            structure  = d.get("structure", "{artist}/{album}/{artist} - {title}"),
            status     = DownloadStatus.PENDING,
        )
    except Exception as exc:
        log.warning(f"[QueuePersistence] No se pudo restaurar tarea: {exc}")
        return None


def save_queue(tasks: List[DownloadTask]) -> int:
    """
    Persist the pending portion of *tasks* to disk.

    Returns:
        The number of tasks written.
    """
    pending = [t for t in tasks if t.status not in _TERMINAL]
    try:
        QUEUE_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(QUEUE_PATH, "w", encoding="utf-8") as fh:
            json.dump(
                {"tasks": [_task_to_dict(t) for t in pending]},
                fh, indent=2, ensure_ascii=False,
            )
        if pending:
            log.info(f"[QueuePersistence] Guardadas {len(pending)} tareas pendientes")
        return len(pending)
    except Exception as exc:
        log.error(f"[QueuePersistence] Error al guardar la cola: {exc}")
        return 0


def load_queue() -> List[DownloadTask]:
    """
    Load previously persisted pending tasks from disk.

    Returns:
        A list of :class:`DownloadTask` (empty if no file or on error).
    """
    if not QUEUE_PATH.exists():
        return []
    try:
        with open(QUEUE_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        raw = data.get("tasks", [])
        tasks = [t for t in (_dict_to_task(d) for d in raw) if t is not None]
        if tasks:
            log.info(f"[QueuePersistence] Restauradas {len(tasks)} tareas pendientes")
        return tasks
    except Exception as exc:
        log.error(f"[QueuePersistence] Error al cargar la cola: {exc}")
        return []


def clear_queue() -> None:
    """Remove the on-disk queue file."""
    try:
        if QUEUE_PATH.exists():
            QUEUE_PATH.unlink()
    except Exception as exc:
        log.warning(f"[QueuePersistence] No se pudo borrar la cola: {exc}")
