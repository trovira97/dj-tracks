"""
downloader/audio_downloader.py
================================
Dual-engine audio download: **spotdl + yt-dlp**.

Engine routing (automatic, no user intervention):

- **Spotify / Apple Music** → primary: **spotdl** (uses the Spotify API for
  exact metadata match, then orchestrates yt-dlp with multiple
  audio-providers and retries).  If spotdl fails or isn't installed,
  falls back to **yt-dlp** with a YouTube text search.
- **SoundCloud / Bandcamp** → **yt-dlp** direct on the source URL (no
  search needed — the URL itself is downloadable, faster, and yields
  authoritative metadata + cover art from the source page).
- **Unknown** → yt-dlp YouTube text search.

Cancellation is implemented via a per-task flag that is checked inside
the progress hooks of both engines.  Active downloads stop at the next
progress callback, which is typically within a second.
"""
from __future__ import annotations

import os
import shutil
import threading
import time
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
        # Global pause flag — when set, progress hooks block until cleared.
        self._paused = threading.Event()
        # Serialise spotdl client construction (SpotifyClient is a singleton).
        self._spotdl_lock    = threading.Lock()
        # Session-level kill switch: once we know spotdl can't work for this
        # session (e.g. the user's Spotify app requires a Premium owner and
        # gets 403 on every search), stop wasting cycles on it.
        self._spotdl_disabled = False
        self._spotdl_reason   = ""

    # ── Pause / resume ────────────────────────────────────────────────────────

    def pause(self) -> None:
        """Pause every active download at the next progress callback."""
        self._paused.set()

    def resume(self) -> None:
        """Resume previously paused downloads."""
        self._paused.clear()

    @property
    def is_paused(self) -> bool:
        return self._paused.is_set()

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
        """yt-dlp progress hook — checks cancellation, honours pause,
        and maps raw byte counts to a 0–100 progress percentage."""
        # Cancellation check: raises to abort the active yt-dlp download.
        with self._flags_lock:
            if self._cancel_flags.get(task.task_id):
                raise _DownloadCancelled()

        # Pause check: block this thread while the global pause flag is set.
        # We re-check cancellation each iteration so the user can still
        # cancel a paused task.
        while self._paused.is_set():
            with self._flags_lock:
                if self._cancel_flags.get(task.task_id):
                    raise _DownloadCancelled()
            time.sleep(0.2)

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

    # ── Engine router ─────────────────────────────────────────────────────────

    # spotdl shines when the source has a real Spotify track ID (or a Spotify
    # URL).  For those it queries the Spotify API for exact metadata and then
    # asks its audio providers (youtube-music, youtube, soundcloud) for the
    # best match — far less prone to "wrong song" hits than a raw text search.
    _SPOTDL_PLATFORMS = {Platform.SPOTIFY.value, Platform.APPLE_MUSIC.value}

    def download(self, task: DownloadTask) -> bool:
        """
        Download the audio for *task*.

        Routes the work to the best engine for the platform.  spotdl is the
        primary engine for Spotify / Apple Music; yt-dlp is primary for
        SoundCloud / Bandcamp (direct URL download) and is also the fallback
        engine when spotdl fails.

        Returns:
            ``True`` on success, ``False`` on error or cancellation.
        """
        # Register the task as not-cancelled before starting.
        with self._flags_lock:
            self._cancel_flags[task.task_id] = False

        track = task.track
        # Honour the session-level kill switch — once spotdl is known to be
        # unusable in this session, every Spotify/Apple task goes straight to
        # yt-dlp without paying the spotdl init / search / 403 round-trip.
        prefer_spotdl = (track.platform in self._SPOTDL_PLATFORMS
                         and not self._spotdl_disabled)

        if prefer_spotdl:
            ok = self._download_spotdl(task)
            if ok or task.status == DownloadStatus.CANCELLED:
                with self._flags_lock:
                    self._cancel_flags.pop(task.task_id, None)
                return ok
            # Silent fallback — only a single info-level note; the loud
            # warning chain comes from spotdl itself and we've already
            # disabled it for this session if appropriate.
            log.info(f"[Downloader] Cayendo a yt-dlp para «{task.display_name}»")
            task.error_msg = ""
            task.progress  = 0.0

        ok = self._download_ytdlp(task)
        with self._flags_lock:
            self._cancel_flags.pop(task.task_id, None)
        return ok

    # ── yt-dlp engine ─────────────────────────────────────────────────────────

    def _download_ytdlp(self, task: DownloadTask) -> bool:
        """yt-dlp engine — direct URL for SoundCloud/Bandcamp, YT text search
        for everything else."""
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
        is_direct = track.platform in direct_url_platforms and bool(track.source_url)
        if is_direct:
            download_url = track.source_url
        else:
            # YouTube text search.  NOTE: yt-dlp only supports "ytsearch" —
            # there is no "ytmusicsearch" scheme.  Audio quality is governed
            # by ydl_opts["format_sort"] below, not by the search prefix.
            download_url = f"ytsearch1:{self._build_yt_query(track)}"

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

        postprocessors = list(profile.yt_dlp_postprocessors())

        ydl_opts: dict = {
            "format":         profile.yt_dlp_format_str(),
            # Always pick the highest-quality audio stream available, preferring
            # lossless codecs, then highest bitrate, then highest sample rate.
            # This is what makes Bandcamp FLAC win over Bandcamp MP3, and YT
            # opus-160 win over m4a-128 on the same video.
            #
            # NOTE: acodec:opus is NOT first any more — YouTube's opus formats
            # now require a JavaScript runtime (Deno/Node) to decode the
            # signature, and without one every "best opus" download returns
            # HTTP 403.  Lossless codecs still win when they exist
            # (Bandcamp FLAC etc.); on YouTube we fall through to abr/asr
            # which picks the best stream the chosen player_client exposes.
            "format_sort":    ["acodec:flac", "acodec:wav", "acodec:alac",
                                "abr", "asr"],
            # YouTube-specific: try player clients that don't need a JS
            # runtime first, then fall back to ones that do.  "mediaconnect"
            # and the android clients return signed URLs that work without
            # Deno/Node — fixes the bulk of "HTTP 403 Forbidden" errors on
            # auto-generated "- Topic" channels (label-uploaded tracks).
            "extractor_args": {
                "youtube": {
                    "player_client": ["mediaconnect", "android", "android_music",
                                       "web_safari", "tv"],
                }
            },
            "outtmpl":        outtmpl,
            "noplaylist":     True,
            "quiet":          True,
            "no_warnings":    True,
            "progress_hooks": [lambda d: self._progress_hook(task, d)],
        }

        # For direct-source platforms (Bandcamp / SoundCloud) the source page
        # carries authoritative metadata + cover art.  Let yt-dlp embed both
        # straight from the source — far more reliable than re-fetching a
        # possibly-stale cover URL from the search API.
        if is_direct:
            postprocessors.append({"key": "FFmpegMetadata", "add_metadata": True})
            postprocessors.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
            ydl_opts["writethumbnail"] = True

        ydl_opts["postprocessors"] = postprocessors
        if self._ffmpeg_path:
            ydl_opts["ffmpeg_location"] = str(Path(self._ffmpeg_path).parent)

        task.status = DownloadStatus.DOWNLOADING
        self._notify(task, 5, "Iniciando descarga…")
        log.info(f"[Downloader yt-dlp] Iniciando: {track.artist_str} — {track.title}")

        # Try the primary attempt; on failure, try a relaxed last-resort that
        # drops the strict format selector and accepts whatever stream the
        # source has.  Many "No video formats found" / format mismatch errors
        # disappear with the loose selector.
        attempts = [
            ("primary",      ydl_opts),
            ("last-resort",  {**ydl_opts,
                               "format":      "bestaudio/best/worstaudio",
                               "format_sort": []}),
        ]

        last_exc: Optional[Exception] = None

        for label, opts in attempts:
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
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
                if label == "last-resort":
                    log.info(f"[Downloader yt-dlp] Completado (last-resort): {task.output_path}")
                else:
                    log.info(f"[Downloader yt-dlp] Completado: {task.output_path}")
                return True

            except _DownloadCancelled:
                task.status    = DownloadStatus.CANCELLED
                task.error_msg = ""
                task.progress  = 0.0
                self._notify(task, 0, "Cancelado")
                log.info(f"[Downloader yt-dlp] Cancelado por el usuario: {track.artist_str} — {track.title}")
                return False

            except Exception as exc:
                last_exc = exc
                log.warning(f"[Downloader yt-dlp] Intento {label} falló: {exc}")
                continue

        # All attempts exhausted.
        task.status    = DownloadStatus.ERROR
        task.error_msg = self._humanise_error(str(last_exc) if last_exc else "Error desconocido")
        self._notify(task, 0, f"Error: {task.error_msg}")
        log.error(f"[Downloader yt-dlp] Error definitivo tras reintentos: {last_exc}")
        return False

    # ── spotdl engine ─────────────────────────────────────────────────────────

    def _download_spotdl(self, task: DownloadTask) -> bool:
        """spotdl engine — primary for Spotify / Apple Music.

        spotdl uses the Spotify API to fetch the canonical metadata for a
        track, then orchestrates yt-dlp across several audio providers
        (youtube-music → youtube → soundcloud) until it finds the best
        match.  Far more reliable than a raw text search for those two
        platforms.

        Returns False (no traceback) on any failure so the caller can fall
        back to plain yt-dlp.
        """
        try:
            from spotdl import Spotdl as _Spotdl
            from spotdl.types.song import Song as _Song
            from spotdl.utils.spotify import SpotifyClient as _SC
        except Exception as exc:
            log.info(f"[Downloader spotdl] No disponible: {exc}")
            return False

        track   = task.track
        profile = task.profile

        # spotdl needs Spotify credentials.  We read them lazily from the
        # main settings.json (same file the controller uses).
        cid, cs = self._read_spotify_creds()
        if not (cid and cs):
            log.info("[Downloader spotdl] Sin credenciales Spotify — fallback a yt-dlp")
            return False

        # Compute the output template that spotdl will use.  Mirror the
        # user's folder structure so spotdl files end up exactly where yt-dlp
        # files would.
        out_path = build_output_path(
            base_folder = task.output_dir,
            artist      = track.artist_str,
            album       = track.album or "Singles",
            title       = track.title,
            ext         = profile.format.value if profile.format.value != "best" else "mp3",
            structure   = task.structure,
        )
        out_path = get_unique_path(out_path)
        out_template = str(out_path.with_suffix(""))   # spotdl appends the codec ext

        fmt     = profile.format.value if profile.format.value != "best" else "mp3"
        bitrate = profile.quality.value if profile.quality.value != "best" else "320k"

        settings = {
            "output":          out_template,
            "format":          fmt,
            "bitrate":         bitrate,
            "threads":         1,             # one task = one download
            "ffmpeg":          self._ffmpeg_path or "ffmpeg",
            "audio_providers": ["youtube-music", "youtube", "soundcloud"],
            "simple_tui":      True,
            "print_errors":    False,
            "log_format":      None,
        }

        task.status = DownloadStatus.DOWNLOADING
        self._notify(task, 5, "Buscando con spotdl…")
        log.info(f"[Downloader spotdl] Iniciando: {track.artist_str} — {track.title}")

        # Spotdl/SpotifyClient is a class-level singleton — reset before
        # building a new client with our credentials.
        try:
            _SC._instance = None
        except Exception:
            pass

        # Silence spotdl + spotipy's noisy stderr loggers — we surface the
        # important failures (with classification) ourselves.
        import logging as _logging
        for _name in ("spotdl", "spotipy", "spotipy.client"):
            try:
                _logging.getLogger(_name).setLevel(_logging.ERROR)
            except Exception:
                pass

        try:
            with self._spotdl_lock:
                client = _Spotdl(
                    client_id=cid, client_secret=cs,
                    downloader_settings=settings,
                )
        except Exception as exc:
            log.info(f"[Downloader spotdl] Init falló: {str(exc)[:120]}")
            return False

        # spotdl needs either a Spotify URL or a query.  Prefer the URL when
        # available; fall back to "Artist - Title" for Apple Music tracks
        # (no spotdl-resolvable URL).
        query = (track.source_url if track.platform == Platform.SPOTIFY.value
                                  and track.source_url
                                 else f"{track.artist_str} - {track.title}")

        try:
            songs = client.search([query])
        except Exception as exc:
            msg = str(exc)
            # Detect terminal Spotify-side failures and disable spotdl for the
            # rest of this session so we don't spam the log on every track.
            low = msg.lower()
            terminal = (
                "premium subscription" in low or
                "403" in low and "api.spotify.com" in low or
                "401" in low or
                "invalid client" in low or
                "invalid_client" in low
            )
            if terminal and not self._spotdl_disabled:
                self._spotdl_disabled = True
                self._spotdl_reason   = msg[:200]
                log.warning(
                    "[Downloader spotdl] Desactivado para esta sesión — la API "
                    "de Spotify rechaza tus credenciales (probablemente la app "
                    "de developer requiere cuenta Premium o el secret es "
                    "inválido). Las descargas seguirán con yt-dlp."
                )
            else:
                log.info(f"[Downloader spotdl] Search falló: {msg[:120]}")
            return False
        if not songs:
            log.info("[Downloader spotdl] Sin resultados — fallback")
            return False

        # spotdl download loop (one song at a time).  We check the cancel
        # flag between calls and via the asyncio.set_event_loop incantation
        # that spotdl requires from a worker thread.
        import asyncio
        try:
            asyncio.set_event_loop(client.downloader.loop)
        except Exception:
            pass

        with self._flags_lock:
            if self._cancel_flags.get(task.task_id):
                raise _DownloadCancelled()

        self._notify(task, 30, "Descargando con spotdl…")
        try:
            results = client.download_songs(songs[:1])
        except Exception as exc:
            log.warning(f"[Downloader spotdl] Download falló: {exc}")
            return False

        if not results:
            return False
        _song, path = results[0]
        if path is None:
            log.info("[Downloader spotdl] No se pudo descargar — fallback")
            return False

        try:
            task.output_path = Path(str(path))
        except Exception:
            task.output_path = None

        task.status   = DownloadStatus.DONE
        task.progress = 100.0
        self._notify(task, 100, "Completado")
        log.info(f"[Downloader spotdl] Completado: {task.output_path}")
        return True

    def _read_spotify_creds(self) -> tuple:
        """Look up Spotify credentials in the standard config locations.

        Same fall-through used by the controller, but we re-implement here
        so the downloader stays decoupled from AppController.
        """
        import json, os as _os
        cid = _os.environ.get("SPOTIFY_CLIENT_ID")     or ""
        cs  = _os.environ.get("SPOTIFY_CLIENT_SECRET") or ""
        if cid and cs:
            return (cid, cs)
        try:
            from utils.paths import config_dir
            cfg_path = config_dir() / "settings.json"
            if cfg_path.exists():
                data = json.loads(cfg_path.read_text(encoding="utf-8"))
                sp = data.get("spotify", {}) or {}
                return (sp.get("client_id", ""), sp.get("client_secret", ""))
        except Exception:
            pass
        return ("", "")

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
        if "drm" in low or "drm protected" in low or "drm-protected" in low:
            return "Audio protegido con DRM — probando en otras plataformas…"
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

    @staticmethod
    def is_drm_error(raw: str) -> bool:
        """True if *raw* looks like a DRM-protected-content failure."""
        if not raw:
            return False
        low = raw.lower()
        return "drm" in low
