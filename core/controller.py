"""
core/controller.py
===================
Central application controller.

Orchestrates search, download, metadata processing, and UI notifications.
Downloads run in a thread pool, so multiple tracks can download concurrently
(bounded by the ``threads`` config key, default 2).
"""
from __future__ import annotations

import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable, Dict, List, Optional

from core.queue_persistence        import load_queue, save_queue
from core.search_manager           import SearchManager
from downloader.audio_downloader   import AudioDownloader, DownloadStatus, DownloadTask
from downloader.quality_manager    import get_profile
from metadata.metadata_writer      import download_cover, verify_and_fix, write_metadata
from providers                     import TrackInfo
from providers.applemusic_provider import AppleMusicProvider
from providers.soundcloud_provider import SoundCloudProvider
from providers.spotify_provider    import SpotifyProvider
from utils.file_utils              import ensure_dir
from utils.logger                  import log
from utils.validators              import Platform


UpdateCallback = Callable[[DownloadTask], None]

# Hard cap on parallel downloads regardless of config value.
_MAX_WORKERS = 4


class AppController:
    """
    Top-level application orchestrator.

    Responsibilities:

    - Load / persist configuration (``config/settings.json``).
    - Construct and manage music providers.
    - Maintain the download queue and a thread-pool worker.
    - Post-process completed downloads (cover art + metadata).
    - Notify the UI layer via an optional :attr:`_on_task_update` callback.
    """

    CONFIG_PATH: Path = Path(__file__).parent.parent / "config" / "settings.json"

    def __init__(self, on_task_update: Optional[UpdateCallback] = None) -> None:
        self._on_task_update: Optional[UpdateCallback] = on_task_update
        self._config: Dict = {}
        self._load_config()

        # Credentials: env vars override the JSON config (more secure for CI / shared boxes).
        sp_id     = os.environ.get("SPOTIFY_CLIENT_ID")     or self._config.get("spotify", {}).get("client_id",     "")
        sp_secret = os.environ.get("SPOTIFY_CLIENT_SECRET") or self._config.get("spotify", {}).get("client_secret", "")
        sc_id     = os.environ.get("SOUNDCLOUD_CLIENT_ID")  or self._config.get("soundcloud", {}).get("client_id",  "")
        am_key    = os.environ.get("APPLE_MUSIC_API_KEY")   or self._config.get("apple_music", {}).get("api_key",   "")

        self.search_manager = SearchManager(
            spotify     = SpotifyProvider(sp_id, sp_secret),
            apple_music = AppleMusicProvider(am_key),
            soundcloud  = SoundCloudProvider(sc_id),
        )
        self.downloader = AudioDownloader(on_progress=self._on_download_progress)

        # Download queue (append-only; tasks are never removed from the list,
        # only their status changes so the UI can reflect the final state).
        self._queue: List[DownloadTask] = []
        self._queue_lock = threading.Lock()

        # Thread pool — max concurrent downloads bounded by config and hard cap.
        max_workers = min(int(self._config.get("threads", 2)), _MAX_WORKERS)
        self._executor = ThreadPoolExecutor(
            max_workers=max(1, max_workers),
            thread_name_prefix="dj-dl",
        )

        # Persisted queue is loaded explicitly by the UI (after callbacks are wired).
        self._restored_tasks: List[DownloadTask] = load_queue()

    # ── Public callback management ────────────────────────────────────────────

    def set_on_task_update(self, callback: Optional[UpdateCallback]) -> None:
        """Register (or clear) the UI notification callback."""
        self._on_task_update = callback

    # ── Configuration ─────────────────────────────────────────────────────────

    def _load_config(self) -> None:
        """Load ``settings.json`` into memory; silently start empty on failure."""
        try:
            with open(self.CONFIG_PATH, encoding="utf-8") as fh:
                self._config = json.load(fh)
            log.info("[Controller] Configuración cargada")
        except FileNotFoundError:
            log.info("[Controller] settings.json no encontrado — usando valores por defecto")
            self._config = {}
        except Exception as exc:
            log.warning(f"[Controller] Error al cargar config: {exc}")
            self._config = {}

    def save_config(self, updates: Dict) -> None:
        """Merge *updates* into the current config and persist to disk."""
        self._config.update(updates)
        try:
            self.CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with open(self.CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(self._config, fh, indent=4, ensure_ascii=False)
            log.info("[Controller] Configuración guardada")
        except Exception as exc:
            log.error(f"[Controller] Error al guardar config: {exc}")

    def get_config(self, key: str, default=None):
        """Return ``config[key]``, or *default* if the key is absent."""
        return self._config.get(key, default)

    def search_diagnostics(self) -> List[str]:
        """Return short warning strings for providers that cannot be used."""
        warnings: List[str] = []
        sp = self._config.get("spotify", {})
        if not (sp.get("client_id") and sp.get("client_secret")):
            warnings.append("Spotify sin credenciales API")
        sc_provider = self.search_manager.provider_for(Platform.SOUNDCLOUD)
        if sc_provider and not getattr(sc_provider, "available", True):
            warnings.append("SoundCloud no disponible")
        return warnings

    # ── Search ────────────────────────────────────────────────────────────────

    def search(
        self,
        query: str,
        platform_str: str = "auto",
        limit: int = 20,
    ) -> List[TrackInfo]:
        mapping: Dict[str, Platform] = {
            "spotify":    Platform.SPOTIFY,
            "applemusic": Platform.APPLE_MUSIC,
            "soundcloud": Platform.SOUNDCLOUD,
            "auto":       Platform.UNKNOWN,
        }
        platform = mapping.get(platform_str.lower(), Platform.UNKNOWN)
        return self.search_manager.search(query, platform=platform, limit=limit)

    def resolve_url(self, url: str) -> List[TrackInfo]:
        """Resolve a platform URL and return the corresponding tracks."""
        return self.search_manager.resolve_url(url)

    # ── Download queue ─────────────────────────────────────────────────────────

    def add_to_queue(self, track: TrackInfo) -> DownloadTask:
        """
        Enqueue *track* for download using the current quality settings.

        Returns:
            The created :class:`~downloader.audio_downloader.DownloadTask`.
        """
        fmt       = self._config.get("preferred_format",  "mp3")
        quality   = self._config.get("preferred_quality", "320k")
        profile   = get_profile(fmt, quality)
        out_dir   = self._config.get("download_folder", "downloads")
        structure = self._config.get(
            "folder_structure", "{artist}/{album}/{artist} - {title}"
        )

        if not Path(out_dir).is_absolute():
            out_dir = str(Path(__file__).parent.parent / out_dir)

        ensure_dir(out_dir)

        task = DownloadTask(
            track      = track,
            profile    = profile,
            output_dir = out_dir,
            structure  = structure,
        )

        with self._queue_lock:
            self._queue.append(task)

        self._notify(task)
        self._executor.submit(self._process_task, task)
        log.info(f"[Controller] Añadido a cola: {task.display_name}")
        return task

    def remove_from_queue(self, task: DownloadTask) -> None:
        """
        Cancel *task* and remove it from the active queue.

        If the task is already downloading, the cancellation signal is sent
        to the downloader; the download will abort at the next progress hook.
        """
        self.downloader.cancel(task.task_id)
        with self._queue_lock:
            try:
                self._queue.remove(task)
            except ValueError:
                pass
        if task.status not in (DownloadStatus.DONE, DownloadStatus.ERROR,
                                DownloadStatus.CANCELLED):
            task.status    = DownloadStatus.CANCELLED
            task.error_msg = ""
            self._notify(task)

    def clear_completed(self) -> None:
        """Remove all DONE / ERROR / CANCELLED tasks from the internal queue."""
        terminal = {DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED}
        with self._queue_lock:
            self._queue = [t for t in self._queue if t.status not in terminal]

    @property
    def queue(self) -> List[DownloadTask]:
        """Thread-safe snapshot of the current download queue."""
        with self._queue_lock:
            return list(self._queue)

    # ── Worker ────────────────────────────────────────────────────────────────

    def _process_task(self, task: DownloadTask) -> None:
        """
        Download and post-process a single task.

        Called by the thread pool; runs in a background thread.
        """
        if task.status == DownloadStatus.CANCELLED:
            return

        task.status = DownloadStatus.DOWNLOADING
        self._notify(task)

        success = self.downloader.download(task)

        if success and task.output_path and self._config.get("auto_fix_metadata", True):
            task.status = DownloadStatus.PROCESSING
            self._notify(task)
            self._post_process(task)

        self._notify(task)

    def _post_process(self, task: DownloadTask) -> None:
        """Write cover art and metadata; verify consistency after download."""
        try:
            path  = task.output_path
            track = task.track
            cover = download_cover(track.cover_url) if track.cover_url else None
            write_metadata(path, track, cover)

            corrections = verify_and_fix(path, track)
            if corrections:
                log.info(f"[Controller] Metadatos corregidos en {path.name}: {corrections}")
        except Exception as exc:
            log.error(f"[Controller] Error en post-proceso: {exc}")

    def shutdown(self) -> None:
        """
        Persist any pending tasks, then shut down the thread pool.

        Called from the UI when the user closes the window.
        """
        # Save the still-pending portion so they're restored next launch.
        with self._queue_lock:
            snapshot = list(self._queue)
        save_queue(snapshot)

        try:
            self._executor.shutdown(wait=False, cancel_futures=True)
        except TypeError:
            # cancel_futures requires Python 3.9+
            self._executor.shutdown(wait=False)

    def resume_restored_queue(self) -> List[DownloadTask]:
        """
        Re-enqueue previously persisted tasks and return them.

        The UI calls this once after registering its update callback so the
        download panel can pre-populate its rows.  Each restored task is
        scheduled on the executor exactly like a freshly added one.
        """
        restored = list(self._restored_tasks)
        self._restored_tasks = []
        for task in restored:
            with self._queue_lock:
                self._queue.append(task)
            self._notify(task)
            self._executor.submit(self._process_task, task)
        if restored:
            log.info(f"[Controller] Re-encoladas {len(restored)} tareas pendientes restauradas")
        return restored

    # ── Callbacks ─────────────────────────────────────────────────────────────

    def _on_download_progress(self, task: DownloadTask, pct: float, msg: str) -> None:
        self._notify(task)

    def _notify(self, task: DownloadTask) -> None:
        """Fire ``_on_task_update`` if a callback is registered."""
        if self._on_task_update:
            try:
                self._on_task_update(task)
            except Exception:
                pass

    # ── Credential hot-swap ────────────────────────────────────────────────────

    def update_spotify_credentials(self, client_id: str, client_secret: str) -> None:
        """Replace the Spotify provider with new credentials (live, no restart)."""
        provider = SpotifyProvider(client_id, client_secret)
        self.search_manager.update_provider(Platform.SPOTIFY, provider)
        self.save_config({"spotify": {"client_id": client_id, "client_secret": client_secret}})
        log.info("[Controller] Credenciales Spotify actualizadas")

    def update_soundcloud_client_id(self, client_id: str) -> None:
        """Replace the SoundCloud provider with a new client ID (live)."""
        provider = SoundCloudProvider(client_id)
        self.search_manager.update_provider(Platform.SOUNDCLOUD, provider)
        self.save_config({"soundcloud": {"client_id": client_id}})
        log.info("[Controller] Client ID SoundCloud actualizado")
