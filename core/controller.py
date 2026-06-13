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
from providers.bandcamp_provider   import BandcampProvider
from providers.soundcloud_provider import SoundCloudProvider
from providers.spotify_provider    import SpotifyProvider
from utils.file_utils              import ensure_dir
from utils.logger                  import log
from utils.paths                   import config_dir
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

    CONFIG_PATH: Path = config_dir() / "settings.json"

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
            bandcamp    = BandcampProvider(),
        )
        self.downloader = AudioDownloader(on_progress=self._on_download_progress)

        # Download queue (append-only; tasks are never removed from the list,
        # only their status changes so the UI can reflect the final state).
        self._queue: List[DownloadTask] = []
        self._queue_lock = threading.Lock()
        self._dedup_lock = threading.Lock()   # guards the shared fingerprint index

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
        """Merge *updates* into the current config and persist atomically."""
        self._config.update(updates)
        try:
            from utils.atomic_io import atomic_write_json
            atomic_write_json(self.CONFIG_PATH, self._config, indent=4)
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
            "bandcamp":   Platform.BANDCAMP,
            "auto":       Platform.UNKNOWN,
        }
        platform = mapping.get(platform_str.lower(), Platform.UNKNOWN)
        return self.search_manager.search(query, platform=platform, limit=limit)

    def resolve_url(self, url: str) -> List[TrackInfo]:
        """Resolve a platform URL and return the corresponding tracks."""
        return self.search_manager.resolve_url(url)

    # ── Download queue ─────────────────────────────────────────────────────────

    # Pretty platform names used when "subfolder_per_platform" is enabled.
    _PLATFORM_SUBDIR = {
        "spotify":    "Spotify",
        "applemusic": "Apple Music",
        "soundcloud": "SoundCloud",
        "bandcamp":   "Bandcamp",
    }

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

        # Optional: prepend a platform sub-folder so Spotify / Apple Music /
        # SoundCloud downloads stay neatly separated.
        if self._config.get("subfolder_per_platform", False):
            plat_dir  = self._PLATFORM_SUBDIR.get(track.platform, "Other")
            structure = f"{plat_dir}/{structure}"

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

    def add_album_to_queue(self, album: TrackInfo) -> int:
        """
        Expand an album/set result into its individual tracks and enqueue
        each one.  Resolves the album's ``source_url`` via the matching
        provider (Spotify album, Apple album, SoundCloud set, Bandcamp album).

        Returns:
            The number of tracks enqueued.
        """
        tracks: List[TrackInfo] = []
        if album.source_url:
            try:
                tracks = self.search_manager.resolve_url(album.source_url)
            except Exception as exc:
                log.error(f"[Controller] No se pudo expandir el álbum «{album.title}»: {exc}")
        # Filter out any album/placeholder entries the resolver might return.
        tracks = [t for t in tracks if t and not getattr(t, "is_album", False)]
        if not tracks:
            log.warning(f"[Controller] Álbum «{album.title}» sin pistas resolubles")
            return 0
        for t in tracks:
            self.add_to_queue(t)
        log.info(f"[Controller] Álbum «{album.title}»: {len(tracks)} pistas en cola")
        return len(tracks)

    def enqueue_result(self, result: TrackInfo) -> int:
        """Enqueue one search result: a whole album if ``is_album``, else a
        single track.  Returns the number of tasks added."""
        if getattr(result, "is_album", False):
            return self.add_album_to_queue(result)
        self.add_to_queue(result)
        return 1

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

        # Bandcamp / SoundCloud download natively from the source page, so
        # yt-dlp already embedded authoritative metadata + cover art.  Running
        # our own post-process would overwrite that with the provider's thinner
        # search-API data (and a sometimes-dead cover URL), so we skip it.
        direct_platforms = {Platform.BANDCAMP.value, Platform.SOUNDCLOUD.value}
        should_post = (
            success
            and task.output_path
            and self._config.get("auto_fix_metadata", True)
            and task.track.platform not in direct_platforms
        )

        # DJ enrichment (BPM / key / Camelot / ReplayGain) applies to EVERY
        # platform — it's independent of where the audio came from.
        dj_enabled = success and task.output_path and self._config.get("dj_enrich", False)

        if should_post or dj_enabled:
            # download() already set DONE; switch to PROCESSING for the metadata
            # pass, then restore DONE so the task reaches a terminal state.
            task.status = DownloadStatus.PROCESSING
            self._notify(task)
            if should_post:
                self._post_process(task)
            if dj_enabled:
                self._dj_enrich(task)
            task.status   = DownloadStatus.DONE
            task.progress = 100.0

        # Acoustic-duplicate guard on the finished file (after enrichment so
        # the final, possibly DJ-renamed file is the one fingerprinted).
        if success and task.output_path and self._config.get("dedupe_audio_fp", False):
            self._dedup_check(task)   # may flip status to ERROR + delete the file

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

    def _dedup_check(self, task: DownloadTask) -> bool:
        """
        Acoustic-duplicate guard.  Computes a Chromaprint fingerprint of the
        finished file and compares it against an index of everything already
        in the download folder.  If it matches an existing track (even with a
        different name / bitrate), the new file is deleted and the task is
        flagged as a duplicate.

        Returns ``True`` if the file was a duplicate and removed.
        Gated by config ``dedupe_audio_fp``; a no-op when disabled.
        """
        if not (task.output_path and self._config.get("dedupe_audio_fp", False)):
            return False
        try:
            from metadata import dj_metadata
        except Exception:
            return False

        ffmpeg = getattr(self.downloader, "_ffmpeg_path", None) or "ffmpeg"
        if not dj_metadata.chromaprint_available(ffmpeg):
            log.info("[Controller] Dedup omitido — este ffmpeg no soporta Chromaprint")
            return False

        fpath  = Path(task.output_path)
        folder = Path(task.output_dir)
        idx_path = folder / ".dj_tracks_fp.json"
        threshold = float(self._config.get("dedupe_audio_fp_threshold", 0.92))

        # Serialise dedup across worker threads (shared index file).
        with self._dedup_lock:
            index: Dict[str, list] = {}
            try:
                if idx_path.exists():
                    index = json.loads(idx_path.read_text(encoding="utf-8")) or {}
            except Exception:
                index = {}

            fp = dj_metadata.chromaprint_fingerprint(str(fpath), ffmpeg)
            if not fp:
                return False
            fp = fp[:200]

            for rel, other in index.items():
                try:
                    if (folder / rel).resolve() == fpath.resolve():
                        continue
                except Exception:
                    pass
                if dj_metadata.fp_similarity(fp, other) >= threshold:
                    # Duplicate — remove the new file and flag the task.
                    try:
                        fpath.unlink()
                    except Exception:
                        return False
                    task.status    = DownloadStatus.ERROR
                    task.error_msg = "♻ Duplicado acústico — ya en tu librería"
                    log.info(f"[Controller] Duplicado eliminado: {fpath.name}")
                    return True

            # Not a duplicate — record its fingerprint.
            try:
                index[str(fpath.relative_to(folder))] = fp
            except Exception:
                index[fpath.name] = fp
            try:
                idx_path.write_text(json.dumps(index), encoding="utf-8")
            except Exception:
                pass
        return False

    def _dj_enrich(self, task: DownloadTask) -> None:
        """
        DJ-grade enrichment: real BPM, musical key + Camelot code, genre,
        optional ReplayGain, optional low-quality flag, and optional
        ``Track [BPM - Camelot]`` filename — via metadata.dj_metadata.

        Gated entirely by config (``dj_enrich``); a no-op when disabled.
        """
        try:
            from metadata import dj_metadata
        except Exception as exc:
            log.error(f"[Controller] dj_metadata no disponible: {exc}")
            return

        track = task.track
        fmt   = task.profile.format.value
        entry = {
            "path":         str(task.output_path),
            "artist":       track.artist_str,
            "title":        track.title,
            "genre":        track.genre,
            "cover_url":    track.cover_url,
            "year":         track.year,
            "track_number": track.track_number,
            "tracks_count": track.total_tracks,
        }
        ffmpeg = getattr(self.downloader, "_ffmpeg_path", None) or "ffmpeg"
        try:
            result = dj_metadata.enrich_files(
                [entry], fmt,
                api_key            = self._config.get("dj_getsongbpm_key", ""),
                use_local_fallback = self._config.get("dj_local_fallback", False),
                requested_quality  = self._config.get("preferred_quality", "320k"),
                check_quality      = self._config.get("dj_quality_check", False),
                embed_covers       = False,   # cover already embedded in metadata pass
                dj_filename        = self._config.get("dj_filename", False),
                replaygain         = self._config.get("dj_replaygain", False),
                ffmpeg             = ffmpeg,
                log                = lambda m, k="info": log.info(f"[DJ] {m.strip()}"),
            )
            # If the DJ-filename option renamed the file, follow the new path.
            renames = result.get("renames", {})
            new_path = renames.get(str(task.output_path))
            if new_path:
                task.output_path = Path(new_path)
            log.info(f"[Controller] DJ enrich: {result.get('tagged', 0)} etiquetado(s)")
        except Exception as exc:
            log.error(f"[Controller] Error en enriquecimiento DJ: {exc}")

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

    # ── Live reconfiguration ──────────────────────────────────────────────────

    def update_thread_count(self, n: int) -> None:
        """
        Resize the download worker pool at runtime.

        Pending tasks already in the old pool are allowed to finish; new
        submissions go to the new pool.  Capped at :data:`_MAX_WORKERS`.
        """
        n = max(1, min(int(n), _MAX_WORKERS))
        old = self._executor
        self._executor = ThreadPoolExecutor(
            max_workers=n,
            thread_name_prefix="dj-dl",
        )
        try:
            old.shutdown(wait=False)
        except Exception:
            pass
        log.info(f"[Controller] Hilos de descarga: {n}")

    def update_ytdlp(self) -> Dict[str, str]:
        """
        Check PyPI for a newer yt-dlp release; install it if there is one.

        YouTube changes its protections every few months and yt-dlp ships
        fixes very fast — keeping it fresh fixes most "HTTP 403" / "video
        unavailable" download failures.

        Returns:
            A dict with keys ``status`` (``up-to-date`` | ``updated`` |
            ``error``), ``current`` (installed version), ``latest``
            (PyPI version when known), and ``message`` (human-friendly).
        """
        import subprocess
        import sys

        # Current version.
        try:
            import yt_dlp
            current = yt_dlp.version.__version__
        except Exception as exc:
            return {"status": "error", "current": "?", "latest": "?",
                    "message": f"yt-dlp no se pudo cargar: {exc}"}

        # Latest version on PyPI.
        latest = "?"
        try:
            import requests
            r = requests.get("https://pypi.org/pypi/yt-dlp/json", timeout=8)
            r.raise_for_status()
            latest = r.json().get("info", {}).get("version", "?")
        except Exception as exc:
            log.warning(f"[Controller] PyPI no accesible: {exc}")
            return {"status": "error", "current": current, "latest": "?",
                    "message": f"No se pudo consultar PyPI: {exc}"}

        # Normalise version strings before comparing.  PyPI reports
        # ``2026.6.9`` while yt-dlp's __version__ is ``2026.06.09`` — same
        # release, different formatting.  Strip leading zeroes from every
        # numeric component so the comparison is on the actual numbers.
        def _norm(v: str) -> tuple:
            parts = []
            for p in v.replace("-", ".").split("."):
                try:
                    parts.append(int(p))
                except ValueError:
                    parts.append(p)
            return tuple(parts)

        if _norm(current) == _norm(latest):
            return {"status": "up-to-date", "current": current,
                    "latest": latest,
                    "message": f"yt-dlp ya está actualizado (v{current})"}

        # Run the upgrade in a SEPARATE Python process and detach.  Replacing
        # yt-dlp while it's still imported in this process can corrupt the
        # interpreter on Windows (locked .pyd files), so we hand pip off and
        # let it finish on its own.  The user is told to restart the app.
        import os as _os
        try:
            # CREATE_NEW_PROCESS_GROUP + DETACHED_PROCESS so the child outlives
            # us cleanly even if the user kills DJ Tracks before pip finishes.
            kwargs: Dict = {}
            if _os.name == "nt":
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
            return {"status": "error", "current": current, "latest": latest,
                    "message": f"No se pudo lanzar el instalador: {exc}"}

        log.info(f"[Controller] yt-dlp upgrade lanzado en segundo plano: "
                 f"{current} → {latest}")
        return {"status": "updated", "current": current, "latest": latest,
                "message": f"Actualizando yt-dlp en segundo plano "
                           f"(v{current} → v{latest}).\n\n"
                           f"Cierra y vuelve a abrir DJ Tracks dentro de "
                           f"30 segundos para usar la nueva versión."}

    def reset_config(self) -> None:
        """Reset configuration to defaults.  Credentials and queue are kept."""
        # Preserve credentials so the user doesn't have to re-enter them.
        keep = {
            "spotify":    self._config.get("spotify",    {}),
            "soundcloud": self._config.get("soundcloud", {}),
            "apple_music": self._config.get("apple_music", {}),
        }
        self._config = dict(keep)
        try:
            from utils.atomic_io import atomic_write_json
            atomic_write_json(self.CONFIG_PATH, self._config, indent=4)
            log.info("[Controller] Configuración restablecida a valores por defecto")
        except Exception as exc:
            log.error(f"[Controller] Error al restablecer config: {exc}")
