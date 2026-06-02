"""
downloader/audio_downloader.py
================================
Audio download engine powered by yt-dlp.

Strategy per platform:

- **SoundCloud**: direct URL download (stream available).
- **Spotify / Apple Music**: YouTube Music text search
  (``ytsearch1:{artist} {title} official audio``).
- **Unknown**: YouTube Music search using whatever metadata is available.

Cancellation is implemented via a per-task flag that is checked
inside yt-dlp's progress hook.  Active downloads stop at the next
progress callback, which is typically within a second.
"""
from __future__ import annotations

import os
import shutil
import threading
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Callable, Dict, Optional

from downloader.quality_manager import QualityProfile, get_profile
from providers import TrackInfo
from utils.file_utils import build_output_path, get_unique_path
from utils.logger import log
from utils.paths import bundled_resource
from utils.validators import Platform


# ─────────────────────────────────────────────────────────────────────────────
# Sentinel exception for mid-download cancellation
# ─────────────────────────────────────────────────────────────────────────────

class _DownloadCancelled(Exception):
    """Raised inside the yt-dlp progress hook to abort an active download."""


# ─────────────────────────────────────────────────────────────────────────────
# Status enum
# ─────────────────────────────────────────────────────────────────────────────

class DownloadStatus(str, Enum):
    """Lifecycle states of a :class:`DownloadTask`."""

    PENDING     = "pending"
    SEARCHING   = "searching"
    DOWNLOADING = "downloading"
    PROCESSING  = "processing"
    DONE        = "done"
    ERROR       = "error"
    CANCELLED   = "cancelled"


# ─────────────────────────────────────────────────────────────────────────────
# Task dataclass
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DownloadTask:
    """
    Represents one item in the download queue.

    Attributes:
        track:       Normalised track metadata from a provider.
        profile:     Audio quality/format preset.
        output_dir:  Root download folder (absolute path string).
        structure:   Folder structure template.
        status:      Current lifecycle state.
        progress:    Download progress 0–100 %.
        output_path: Final file path once the download completes.
        error_msg:   Human-readable error description on failure.
        task_id:     Unique hex identifier for this task.
    """

    track:       TrackInfo
    profile:     QualityProfile
    output_dir:  str
    structure:   str            = "{artist}/{album}/{artist} - {title}"
    status:      DownloadStatus = DownloadStatus.PENDING
    progress:    float          = 0.0
    output_path: Optional[Path] = None
    error_msg:   str            = ""
    task_id:     str            = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def display_name(self) -> str:
        """Short human-readable name: ``Artist — Title``."""
        return f"{self.track.artist_str} — {self.track.title}"


ProgressCallback = Callable[[DownloadTask, float, str], None]


# ─────────────────────────────────────────────────────────────────────────────
# Downloader
# ─────────────────────────────────────────────────────────────────────────────

class AudioDownloader:
    """
    Multi-source audio downloader backed by yt-dlp.

    Thread-safe: multiple tasks can download concurrently because each
    call to :meth:`download` uses its own ``YoutubeDL`` instance.
    The only shared state is the ``_cancel_flags`` dict, protected by a lock.
    """

    _AUDIO_SUFFIXES = frozenset({".mp3", ".flac", ".wav", ".ogg", ".m4a", ".opus"})

    def __init__(
        self,
        on_progress: Optional[ProgressCallback] = None,
        ffmpeg_path: Optional[str] = None,
    ) -> None:
        self._on_progress  = on_progress
        self._ffmpeg_path  = ffmpeg_path or self._find_ffmpeg()
        self._cancel_flags: Dict[str, bool] = {}
        self._flags_lock   = threading.Lock()

    # ── FFmpeg detection ──────────────────────────────────────────────────────

    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        """
        Locate a usable ffmpeg binary.

        Checks (in order):
        1. System ``PATH`` via ``shutil.which``.
        2. spotdl's standard install locations.
        3. A ``ffmpeg.exe`` bundled alongside this project.
        """
        if shutil.which("ffmpeg"):
            return "ffmpeg"

        home   = Path.home()
        suffix = ".exe" if os.name == "nt" else ""
        candidates = [
            bundled_resource(f"ffmpeg{suffix}"),          # frozen exe / source root
            home / ".spotdl"        / f"ffmpeg{suffix}",
            home / ".config/spotdl" / f"ffmpeg{suffix}",
        ]
        for c in candidates:
            if c.exists():
                return str(c)

        log.warning("[Downloader] ffmpeg no encontrado — la conversión de audio no estará disponible")
        return None

    # ── Core download ─────────────────────────────────────────────────────────

    def _build_yt_query(self, track: TrackInfo) -> str:
        """Build a YouTube Music search query optimised for audio quality.

        Adding "official audio" steers results to the cleanest source upload
        (no fan videos, no live versions, no lyrics karaoke).
        """
        return f"{track.artist_str} {track.title} official audio"

    def _progress_hook(self, task: DownloadTask, d: dict) -> None:
        """yt-dlp progress hook — checks cancellation and maps progress to 0–100."""
        # Cancellation check: raises to abort the active yt-dlp download.
        with self._flags_lock:
            if self._cancel_flags.get(task.task_id):
                raise _DownloadCancelled()

        status = d.get("status")
        if status == "downloading":
            total      = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            downloaded = d.get("downloaded_bytes", 0)
            pct        = (downloaded / total * 100) if total else 0
            speed      = d.get("_speed_str", "")
            self._notify(task, pct, f"Descargando {pct:.0f}% {speed}".strip())
        elif status == "finished":
            self._notify(task, 95, "Procesando audio…")

    def _notify(self, task: DownloadTask, pct: float, msg: str) -> None:
        task.progress = pct
        if self._on_progress:
            try:
                self._on_progress(task, pct, msg)
            except Exception:
                pass

    def download(self, task: DownloadTask) -> bool:
        """
        Download the audio for *task*.

        Returns:
            ``True`` on success, ``False`` on error or cancellation.

        Side effects:
            Updates ``task.status``, ``task.progress``, ``task.output_path``,
            and ``task.error_msg`` in-place.
        """
        try:
            import yt_dlp  # type: ignore[import]
        except ImportError:
            task.status    = DownloadStatus.ERROR
            task.error_msg = "yt-dlp no está instalado"
            log.error("[Downloader] yt-dlp no disponible")
            return False

        track   = task.track
        profile = task.profile

        # Platforms whose source_url can be handed straight to yt-dlp
        # (no YouTube fallback needed because yt-dlp downloads from them
        # natively, often at higher quality than YT).
        direct_url_platforms = {
            Platform.SOUNDCLOUD.value,
            Platform.BANDCAMP.value,
        }
        if track.platform in direct_url_platforms and track.source_url:
            download_url = track.source_url
        else:
            # YouTube Music search yields better audio streams (opus 160 kbps)
            # than plain YouTube search (often opus 128 / m4a 128).
            download_url = f"ytmusicsearch1:{self._build_yt_query(track)}"

        out_path = build_output_path(
            base_folder = task.output_dir,
            artist      = track.artist_str,
            album       = track.album or "Singles",
            title       = track.title,
            ext         = profile.format.value if profile.format.value != "best" else "%(ext)s",
            structure   = task.structure,
        )
        out_path = get_unique_path(out_path)
        outtmpl  = str(out_path.with_suffix("")) + ".%(ext)s"

        ydl_opts: dict = {
            "format":         profile.yt_dlp_format_str(),
            # Always pick the highest-quality audio stream available, preferring
            # lossless codecs, then highest bitrate, then highest sample rate.
            # This is what makes Bandcamp FLAC win over Bandcamp MP3, and YT
            # opus-160 win over m4a-128 on the same video.
            "format_sort":    ["acodec:flac", "acodec:wav", "acodec:alac",
                                "acodec:opus", "abr", "asr"],
            "outtmpl":        outtmpl,
            "noplaylist":     True,
            "quiet":          True,
            "no_warnings":    True,
            "progress_hooks": [lambda d: self._progress_hook(task, d)],
            "postprocessors": profile.yt_dlp_postprocessors(),
        }
        if self._ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(Path(self._ffmpeg_path).parent)

        # Register the task as not-cancelled before starting.
        with self._flags_lock:
            self._cancel_flags[task.task_id] = False

        task.status = DownloadStatus.DOWNLOADING
        self._notify(task, 5, "Iniciando descarga…")
        log.info(f"[Downloader] Iniciando: {track.artist_str} — {track.title}")

        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([download_url])

            # Locate the output file by stem (yt-dlp may change the extension).
            parent = out_path.parent
            stem   = out_path.stem
            for candidate in parent.glob(f"{stem}.*"):
                if candidate.suffix.lower() in self._AUDIO_SUFFIXES:
                    task.output_path = candidate
                    break

            task.status   = DownloadStatus.DONE
            task.progress = 100.0
            self._notify(task, 100, "Completado")
            log.info(f"[Downloader] Completado: {task.output_path}")
            return True

        except _DownloadCancelled:
            task.status    = DownloadStatus.CANCELLED
            task.error_msg = ""
            task.progress  = 0.0
            self._notify(task, 0, "Cancelado")
            log.info(f"[Downloader] Cancelado por el usuario: {track.artist_str} — {track.title}")
            return False

        except Exception as exc:
            task.status    = DownloadStatus.ERROR
            task.error_msg = self._humanise_error(str(exc))
            self._notify(task, 0, f"Error: {task.error_msg}")
            log.error(f"[Downloader] Error: {exc}")
            return False

        finally:
            # Clean up the flag entry.
            with self._flags_lock:
                self._cancel_flags.pop(task.task_id, None)

    def cancel(self, task_id: str) -> None:
        """
        Signal that the download for *task_id* should stop.

        The download will abort at the next yt-dlp progress callback,
        typically within a second of this call.
        """
        with self._flags_lock:
            self._cancel_flags[task_id] = True

    # ── Error mapping ─────────────────────────────────────────────────────────

    @staticmethod
    def _humanise_error(raw: str) -> str:
        """
        Map raw yt-dlp / ffmpeg errors to short, friendly Spanish messages.

        Long tracebacks make the queue rows unreadable; a short tag plus the
        last meaningful line keeps the row tidy while logs still capture the
        full detail.
        """
        low = raw.lower()
        if "403" in low or "forbidden" in low:
            return "Acceso denegado (403) — vídeo restringido o yt-dlp desactualizado"
        if "404" in low or "not found" in low:
            return "No se encontró el contenido (404)"
        if "429" in low or "too many requests" in low:
            return "Rate limit alcanzado — espera unos minutos"
        if "age-restricted" in low or "sign in to confirm" in low:
            return "Vídeo con restricción de edad"
        if "private video" in low:
            return "Vídeo privado"
        if "members-only" in low or "premium" in low:
            return "Contenido sólo para miembros / premium"
        if "geo" in low and ("restrict" in low or "block" in low):
            return "Bloqueado en tu región"
        if "ffmpeg" in low:
            return "Error de conversión de audio (ffmpeg)"
        if "no such file" in low or "permission denied" in low:
            return "Error de escritura en disco — revisa la carpeta de destino"
        if "network" in low or "timed out" in low or "connection" in low:
            return "Error de red — verifica tu conexión"

        # Fallback: keep only the last line so the row stays readable.
        last = raw.strip().splitlines()[-1] if raw.strip() else "Error desconocido"
        return last[:140]
