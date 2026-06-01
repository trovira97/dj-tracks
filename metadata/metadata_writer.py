"""
metadata/metadata_writer.py
============================
Write and verify audio metadata using Mutagen.

Supports MP3 (ID3v2.3), FLAC (VorbisComment + Picture),
M4A / AAC (MP4 atoms), and OGG Vorbis.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, Optional, Tuple

import requests
from mutagen.flac import FLAC, Picture
from mutagen.id3 import (
    APIC, ID3, ID3NoHeaderError,
    TALB, TDRC, TCON, TIT2, TPE1, TPE2, TSRC,
)
from mutagen.mp4 import MP4, MP4Cover
from mutagen.oggvorbis import OggVorbis

from metadata.metadata_reader import AudioMetadata, read_metadata
from providers import TrackInfo
from utils.logger import log

# Maximum cover image size to accept (10 MB).
_MAX_COVER_BYTES = 10 * 1024 * 1024


# ─────────────────────────────────────────────────────────────────────────────
# Cover art
# ─────────────────────────────────────────────────────────────────────────────

def download_cover(url: str, timeout: int = 10) -> Optional[bytes]:
    """
    Fetch cover art bytes from *url*.

    Validates Content-Type and enforces a size limit to prevent
    unexpectedly large responses from being embedded.

    Args:
        url:     HTTP(S) URL of the cover image.
        timeout: Request timeout in seconds.

    Returns:
        Raw image bytes on success, or ``None`` on any error.
    """
    if not url:
        return None
    try:
        resp = requests.get(url, timeout=timeout)
        resp.raise_for_status()

        ct = resp.headers.get("Content-Type", "")
        if ct and "image" not in ct:
            log.warning(f"[MetadataWriter] URL de portada no es imagen (Content-Type: {ct}): {url}")
            return None

        if len(resp.content) > _MAX_COVER_BYTES:
            log.warning(f"[MetadataWriter] Portada demasiado grande ({len(resp.content)} B), omitida")
            return None

        return resp.content
    except Exception as exc:
        log.warning(f"[MetadataWriter] No se pudo descargar portada: {exc}")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public write entry point
# ─────────────────────────────────────────────────────────────────────────────

def write_metadata(
    path: Path,
    track: TrackInfo,
    cover_data: Optional[bytes] = None,
) -> bool:
    """
    Write complete metadata from *track* into the audio file at *path*.

    Dispatches to the correct format handler based on the file extension.

    Args:
        path:       Absolute path to the audio file.
        track:      Normalised track metadata.
        cover_data: Raw bytes of the cover image (``None`` to skip).

    Returns:
        ``True`` on success, ``False`` on any error.
    """
    handlers = {
        ".mp3":  _write_mp3,
        ".flac": _write_flac,
        ".m4a":  _write_m4a,
        ".mp4":  _write_m4a,
        ".aac":  _write_m4a,
        ".ogg":  _write_ogg,
    }
    handler = handlers.get(path.suffix.lower())
    if not handler:
        log.warning(f"[MetadataWriter] Formato no soportado: {path.suffix}")
        return False
    try:
        return handler(path, track, cover_data)
    except Exception as exc:
        log.error(f"[MetadataWriter] Error al escribir metadatos en {path.name}: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Format-specific writers
# ─────────────────────────────────────────────────────────────────────────────

def _write_mp3(path: Path, track: TrackInfo, cover: Optional[bytes]) -> bool:
    """Write ID3v2.3 tags to an MP3 file."""
    try:
        try:
            tags = ID3(str(path))
        except ID3NoHeaderError:
            tags = ID3()

        tags.delall("TIT2"); tags.add(TIT2(text=[track.title]))
        tags.delall("TPE1"); tags.add(TPE1(text=[track.artist_str]))
        tags.delall("TPE2"); tags.add(TPE2(text=[track.artist_str]))
        tags.delall("TALB"); tags.add(TALB(text=[track.album or ""]))

        if track.year:
            tags.delall("TDRC"); tags.add(TDRC(text=[track.year]))
        if track.genre:
            tags.delall("TCON"); tags.add(TCON(text=[track.genre]))
        if track.isrc:
            tags.delall("TSRC"); tags.add(TSRC(text=[track.isrc]))

        if cover:
            tags.delall("APIC")
            tags.add(APIC(
                encoding=3, mime="image/jpeg",
                type=3, desc="Cover", data=cover,
            ))

        tags.save(str(path), v2_version=3)
        return True
    except Exception as exc:
        log.error(f"[MetadataWriter] Error MP3: {exc}")
        return False


def _write_flac(path: Path, track: TrackInfo, cover: Optional[bytes]) -> bool:
    """Write VorbisComment tags (and optional cover Picture) to a FLAC file."""
    try:
        audio = FLAC(str(path))
        audio["title"]  = [track.title]
        audio["artist"] = [track.artist_str]
        audio["album"]  = [track.album or ""]
        if track.year:
            audio["date"] = [track.year]
        if track.genre:
            audio["genre"] = [track.genre]
        if track.isrc:
            audio["isrc"] = [track.isrc]

        if cover:
            audio.clear_pictures()
            pic       = Picture()
            pic.type  = 3
            pic.mime  = "image/jpeg"
            pic.desc  = "Cover"
            pic.data  = cover
            audio.add_picture(pic)

        audio.save()
        return True
    except Exception as exc:
        log.error(f"[MetadataWriter] Error FLAC: {exc}")
        return False


def _write_m4a(path: Path, track: TrackInfo, cover: Optional[bytes]) -> bool:
    """Write MP4 atoms to an M4A / AAC file."""
    try:
        audio = MP4(str(path))
        audio["\xa9nam"] = [track.title]
        audio["\xa9ART"] = [track.artist_str]
        audio["\xa9alb"] = [track.album or ""]
        if track.year:
            audio["\xa9day"] = [track.year]
        if track.genre:
            audio["\xa9gen"] = [track.genre]
        if cover:
            audio["covr"] = [MP4Cover(cover, imageformat=MP4Cover.FORMAT_JPEG)]

        audio.save()
        return True
    except Exception as exc:
        log.error(f"[MetadataWriter] Error M4A: {exc}")
        return False


def _write_ogg(path: Path, track: TrackInfo, cover: Optional[bytes]) -> bool:
    """Write VorbisComment tags to an OGG Vorbis file (cover not embedded)."""
    try:
        audio = OggVorbis(str(path))
        audio["title"]  = [track.title]
        audio["artist"] = [track.artist_str]
        audio["album"]  = [track.album or ""]
        if track.year:
            audio["date"] = [track.year]
        if track.genre:
            audio["genre"] = [track.genre]
        audio.save()
        return True
    except Exception as exc:
        log.error(f"[MetadataWriter] Error OGG: {exc}")
        return False


# ─────────────────────────────────────────────────────────────────────────────
# Verification & auto-fix
# ─────────────────────────────────────────────────────────────────────────────

def verify_and_fix(path: Path, track: TrackInfo) -> Dict[str, Tuple[str, str]]:
    """
    Compare the on-disk metadata against *track* and rewrite if discrepancies
    are found.

    Only title, artist, album, and year are checked.

    Returns:
        Dict mapping field name → ``(old_value, new_value)`` for each
        corrected field.  Empty dict means no corrections were needed.
    """
    current: Optional[AudioMetadata] = read_metadata(path)
    if not current:
        log.warning(f"[MetadataWriter] No se pudieron leer metadatos de {path.name}")
        return {}

    def _differs(a: str, b: str) -> bool:
        return (a or "").strip().lower() != (b or "").strip().lower()

    corrections: Dict[str, Tuple[str, str]] = {}
    checks = [
        ("title",  current.title,      track.title),
        ("artist", current.artist_str, track.artist_str),
        ("album",  current.album,      track.album),
        ("year",   current.year,       track.year),
    ]
    for field_name, current_val, expected_val in checks:
        if _differs(current_val, expected_val):
            corrections[field_name] = (current_val, expected_val)

    if corrections:
        log.info(
            f"[MetadataWriter] Corrigiendo {len(corrections)} campo(s) en "
            f"{path.name}: {list(corrections)}"
        )
        cover = download_cover(track.cover_url) if track.cover_url else None
        write_metadata(path, track, cover)

    return corrections
