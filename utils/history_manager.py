"""
utils/history_manager.py
=========================
Persistent download history stored as JSON.

Records every completed or failed download; provides statistics,
filtering, and export to CSV / JSON.  Thread-safe: all mutating
operations are protected by an internal lock so they can be called
from concurrent download workers.
"""
from __future__ import annotations

import csv
import json
import threading
import uuid
from datetime import datetime, date
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from utils.logger import log
from utils.paths  import config_dir


HISTORY_PATH = config_dir() / "history.json"

# Maximum number of records kept in memory and on disk.
_MAX_RECORDS = 2_000


class DownloadRecord:
    """Single entry in the download history."""

    __slots__ = (
        "id", "timestamp", "title", "artist", "album",
        "platform", "quality", "status", "path", "duration_ms", "error",
    )

    def __init__(
        self,
        title: str,
        artist: str,
        album: str,
        platform: str,
        quality: str,
        status: str,          # "done" | "error"
        path: str = "",
        duration_ms: int = 0,
        error: str = "",
        record_id: str = "",
        timestamp: str = "",
    ) -> None:
        self.id          = record_id or uuid.uuid4().hex
        self.timestamp   = timestamp or datetime.now().isoformat(timespec="seconds")
        self.title       = title
        self.artist      = artist
        self.album       = album
        self.platform    = platform
        self.quality     = quality
        self.status      = status
        self.path        = path
        self.duration_ms = duration_ms
        self.error       = error

    def to_dict(self) -> Dict:
        return {k: getattr(self, k) for k in self.__slots__}

    @classmethod
    def from_dict(cls, d: Dict) -> "DownloadRecord":
        return cls(
            title       = d.get("title", ""),
            artist      = d.get("artist", ""),
            album       = d.get("album", ""),
            platform    = d.get("platform", ""),
            quality     = d.get("quality", ""),
            status      = d.get("status", "done"),
            path        = d.get("path", ""),
            duration_ms = d.get("duration_ms", 0),
            error       = d.get("error", ""),
            record_id   = d.get("id", ""),
            timestamp   = d.get("timestamp", ""),
        )

    @property
    def date_str(self) -> str:
        try:
            return self.timestamp[:10]
        except Exception:
            return ""


class HistoryManager:
    """
    Manages the persistent download history.

    All public methods are thread-safe and can be called from any thread.
    """

    def __init__(self) -> None:
        self._records: List[DownloadRecord] = []
        self._lock = threading.Lock()
        self._load()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        """Load history from disk.  Called once at construction."""
        try:
            with open(HISTORY_PATH, encoding="utf-8") as fh:
                data = json.load(fh)
            self._records = [DownloadRecord.from_dict(d) for d in data.get("downloads", [])]
        except FileNotFoundError:
            self._records = []
        except (json.JSONDecodeError, Exception) as exc:
            log.error(f"[History] No se pudo cargar el historial: {exc}")
            self._records = []

    def _save_snapshot(self, records: List[DownloadRecord]) -> None:
        """Persist *records* to disk.  Called outside the lock."""
        try:
            HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(HISTORY_PATH, "w", encoding="utf-8") as fh:
                json.dump(
                    {"downloads": [r.to_dict() for r in records]},
                    fh, indent=2, ensure_ascii=False,
                )
        except PermissionError as exc:
            log.error(f"[History] Sin permisos para escribir en {HISTORY_PATH}: {exc}")
        except OSError as exc:
            log.error(f"[History] Error de disco al guardar historial: {exc}")
        except Exception as exc:
            log.error(f"[History] Error inesperado al guardar historial: {exc}")

    # ── Write ─────────────────────────────────────────────────────────────────

    def add_from_task(self, task) -> None:
        """
        Record a completed or failed DownloadTask.

        Thread-safe.  Args:
            task: A :class:`~downloader.audio_downloader.DownloadTask` instance.
        """
        from downloader.audio_downloader import DownloadStatus
        status = "done" if task.status == DownloadStatus.DONE else "error"
        rec = DownloadRecord(
            title       = task.track.title,
            artist      = task.track.artist_str,
            album       = task.track.album or "",
            platform    = task.track.platform,
            quality     = task.profile.label,
            status      = status,
            path        = str(task.output_path) if task.output_path else "",
            duration_ms = task.track.duration_ms,
            error       = task.error_msg or "",
        )
        with self._lock:
            self._records.insert(0, rec)          # newest first
            if len(self._records) > _MAX_RECORDS:
                self._records = self._records[:_MAX_RECORDS]
            snapshot = list(self._records)

        self._save_snapshot(snapshot)

    # ── Read ──────────────────────────────────────────────────────────────────

    def all(self) -> List[DownloadRecord]:
        with self._lock:
            return list(self._records)

    def filter(
        self,
        query: str = "",
        platform: str = "",
        status: str = "",
        page: int = 0,
        page_size: int = 50,
    ) -> Tuple[List[DownloadRecord], int]:
        """
        Return ``(records_page, total_count)`` filtered by query / platform / status.
        """
        with self._lock:
            results = list(self._records)

        if query:
            q = query.lower()
            results = [r for r in results if q in r.title.lower() or q in r.artist.lower()]
        if platform:
            results = [r for r in results if r.platform == platform]
        if status:
            results = [r for r in results if r.status == status]

        total = len(results)
        start = page * page_size
        return results[start: start + page_size], total

    # ── Statistics ─────────────────────────────────────────────────────────────

    def stats(self) -> Dict:
        """Return aggregated statistics (thread-safe snapshot)."""
        with self._lock:
            records = list(self._records)

        today       = date.today().isoformat()
        total       = len(records)
        done        = sum(1 for r in records if r.status == "done")
        today_n     = sum(1 for r in records if r.date_str == today)
        success_pct = round(done / total * 100) if total else 0

        plat_count: Dict[str, int] = {}
        for r in records:
            plat_count[r.platform] = plat_count.get(r.platform, 0) + 1

        return {
            "total":       total,
            "done":        done,
            "errors":      total - done,
            "today":       today_n,
            "success_pct": success_pct,
            "by_platform": plat_count,
        }

    def recent(self, n: int = 5) -> List[DownloadRecord]:
        with self._lock:
            return self._records[:n]

    # ── Export ────────────────────────────────────────────────────────────────

    def export_csv(self, path: Path) -> int:
        """Write all records to *path* as CSV.  Returns number of rows written."""
        fields = ["timestamp", "status", "title", "artist", "album",
                  "platform", "quality", "duration_ms", "path", "error"]
        records = self.all()
        with open(path, "w", newline="", encoding="utf-8") as fh:
            writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
            writer.writeheader()
            for r in records:
                writer.writerow(r.to_dict())
        return len(records)

    def export_json(self, path: Path) -> int:
        """Write all records to *path* as pretty-printed JSON.  Returns count."""
        records = self.all()
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(
                {"exports": len(records), "downloads": [r.to_dict() for r in records]},
                fh, indent=2, ensure_ascii=False,
            )
        return len(records)

    def clear(self) -> None:
        """Remove all records from memory and disk."""
        with self._lock:
            self._records.clear()
        self._save_snapshot([])
