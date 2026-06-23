"""
providers/youtube_provider.py
==============================
YouTube provider — URL resolution + text search via yt-dlp.

YouTube is already supported by yt-dlp for the actual download.  This
provider only resolves a pasted URL (single video or playlist) into
TrackInfo objects so the rest of the pipeline (queue, downloader,
history, DJ enrichment) can treat YouTube like any other source.

Text search is also wired in — uses yt-dlp's ``ytsearchN:`` extractor
so we don't need a YouTube Data API key.
"""
from __future__ import annotations

import re

from providers import MusicProvider, TrackInfo
from utils.logger import log

# Quick guess at "artist - title" from a video title.  YouTube videos
# overwhelmingly follow the "Artist - Title (Official Video)" pattern;
# this is a best-effort split, never an assertion.
_TITLE_SPLIT_RE = re.compile(r"\s+[-–—]\s+", re.U)

# Things that make a video less likely to be a music track.  Search
# results matching these are de-prioritised but NOT dropped (user might
# specifically want a live set or a podcast).
_NOISE_TAGS = ("(official video)", "(official music video)", "[official video]",
               "(audio)", "(lyrics)", "(lyric video)", "[official audio]",
               "[official]", "(official)", "[hd]", "(hd)", "(mv)", "[mv]")


def _clean_title(raw: str) -> str:
    t = (raw or "").strip()
    low = t.lower()
    for tag in _NOISE_TAGS:
        if tag in low:
            i = low.index(tag)
            t = t[:i].strip()
            low = t.lower()
    return t


def _split_artist_title(video_title: str, uploader: str) -> tuple[str, str]:
    """Best-effort artist + title extraction from a YouTube video title.

    Falls back to the uploader as artist when the title doesn't carry a
    clear "Artist - Title" separator.  Strips "- Topic" suffix that
    YouTube Music auto-generates for label channels.
    """
    cleaned = _clean_title(video_title)
    parts = _TITLE_SPLIT_RE.split(cleaned, maxsplit=1)
    if len(parts) == 2:
        artist, title = parts[0].strip(), parts[1].strip()
        if artist and title:
            return artist, title
    # No separator — keep the title intact, use the uploader as artist.
    uploader = (uploader or "").strip()
    if uploader.endswith(" - Topic"):
        uploader = uploader[: -len(" - Topic")].strip()
    return (uploader or "Unknown"), (cleaned or "Unknown")


def _best_thumbnail(thumbnails: list) -> str:
    """Pick the largest thumbnail URL from yt-dlp's list."""
    if not thumbnails:
        return ""
    try:
        # yt-dlp returns them in ascending quality order; take the last
        # one that has a width (preferred) or just the last entry.
        with_w = [t for t in thumbnails if t.get("width")]
        chosen = (with_w or thumbnails)[-1]
        return chosen.get("url", "") or ""
    except Exception:
        return ""


def _entry_to_info(entry: dict) -> TrackInfo | None:
    if not isinstance(entry, dict):
        return None
    try:
        video_id = entry.get("id") or ""
        title    = entry.get("track") or entry.get("title") or ""
        uploader = entry.get("artist") or entry.get("uploader") or entry.get("channel") or ""
        # When yt-dlp picked up structured "track"/"artist" tags (YT
        # Music or label uploads) use them verbatim; otherwise fall back
        # to title splitting.
        if entry.get("track") and (entry.get("artist") or entry.get("creator")):
            artist = entry.get("artist") or entry.get("creator") or "Unknown"
            song   = entry.get("track")
        else:
            artist, song = _split_artist_title(title, uploader)

        url = (entry.get("webpage_url")
               or entry.get("url")
               or (f"https://www.youtube.com/watch?v={video_id}" if video_id else ""))
        if not url:
            return None

        album = (entry.get("album") or "").strip()
        return TrackInfo(
            title       = song,
            artists     = [artist],
            album       = album,
            cover_url   = _best_thumbnail(entry.get("thumbnails") or []),
            source_url  = url,
            platform    = "youtube",
            track_id    = video_id,
            duration_ms = int((entry.get("duration") or 0) * 1000) or 0,
        )
    except Exception as exc:
        log.warning(f"[YouTube] No se pudo convertir entrada: {exc}")
        return None


class YouTubeProvider(MusicProvider):
    """YouTube provider backed by yt-dlp's metadata extraction.

    Always available (yt-dlp is a hard dependency of the downloader).
    No API key needed.
    """

    _PLAYLIST_RE = re.compile(r"[?&]list=([\w-]+)", re.I)

    def __init__(self) -> None:
        self._available = self._yt_dlp_available()
        if self._available:
            log.info("[YouTube] Cliente iniciado (yt-dlp metadata)")
        else:
            log.warning("[YouTube] yt-dlp no disponible — provider inactivo")

    @staticmethod
    def _yt_dlp_available() -> bool:
        try:
            import yt_dlp  # noqa: F401
            return True
        except Exception:
            return False

    @property
    def name(self) -> str:
        return "YouTube"

    @property
    def available(self) -> bool:
        return self._available

    # ── Low-level yt-dlp call ────────────────────────────────────────────────
    @staticmethod
    def _extract(url_or_query: str, *, flat: bool = False) -> dict | None:
        """Run yt-dlp's extract_info without downloading."""
        try:
            import yt_dlp
            opts = {
                "quiet":         True,
                "no_warnings":   True,
                "skip_download": True,
                "extract_flat":  "in_playlist" if flat else False,
                "noprogress":    True,
                # Lighter player_client list for metadata-only — avoids
                # the slower mediaconnect path on simple watch URLs.
                "extractor_args": {"youtube": {"player_client": ["android", "web"]}},
            }
            with yt_dlp.YoutubeDL(opts) as ydl:
                return ydl.extract_info(url_or_query, download=False)
        except Exception as exc:
            log.warning(f"[YouTube] extract_info falló para «{url_or_query}»: {exc}")
            return None

    # ── MusicProvider ───────────────────────────────────────────────────────

    def search(self, query: str, limit: int = 10) -> list[TrackInfo]:
        if not query.strip() or not self._available:
            return []
        # ytsearch{N}: returns N flat entries with title/uploader/url.
        # We then extract_info each to enrich with thumbnails / duration,
        # but only for the top results so a 50-item search doesn't spawn
        # 50 round trips.
        info = self._extract(f"ytsearch{limit}:{query}", flat=True)
        if not info or "entries" not in info:
            return []
        out: list[TrackInfo] = []
        for entry in info["entries"]:
            ti = _entry_to_info(entry)
            if ti:
                out.append(ti)
            if len(out) >= limit:
                break
        return out

    def get_track(self, url_or_id: str) -> TrackInfo | None:
        if not self._available:
            return None
        url = url_or_id
        if not url.startswith("http"):
            url = f"https://www.youtube.com/watch?v={url_or_id}"
        info = self._extract(url, flat=False)
        if not info:
            return None
        return _entry_to_info(info)

    def get_tracks_from_url(self, url: str) -> list[TrackInfo]:
        """Resolve a YouTube URL.

        - Single video           → list of one TrackInfo (full metadata).
        - Playlist URL           → list of one TrackInfo per video (flat
                                   extraction so we don't hammer YT with
                                   N detail requests up-front).
        - Channel / topic / etc. → empty list (the queue isn't the
                                   right place for "play this artist's
                                   whole catalogue").
        """
        if not self._available:
            return []
        is_playlist = bool(self._PLAYLIST_RE.search(url))
        info = self._extract(url, flat=is_playlist)
        if not info:
            return []
        if is_playlist and "entries" in info:
            out: list[TrackInfo] = []
            for entry in info["entries"]:
                ti = _entry_to_info(entry)
                if ti:
                    out.append(ti)
            return out
        # Single video.
        ti = _entry_to_info(info)
        return [ti] if ti else []
