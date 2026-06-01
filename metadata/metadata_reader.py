"""
metadata/metadata_reader.py
============================
Read audio metadata from files using Mutagen.

Supports MP3 (ID3), FLAC (VorbisComment), WAV, OGG Vorbis, and M4A/AAC.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional

from utils.logger import log


@dataclass
class AudioMetadata:
    """Metadata read from an audio file."""

    title:    str        = ""
    artists:  List[str]  = field(default_factory=list)
    album:    str        = ""
    year:     str        = ""
    genre:    str        = ""
    isrc:     str        = ""
    track_n:  int        = 0
    cover:    bytes      = field(default_factory=bytes)
    bitrate:  int        = 0    # kbps
    duration: float      = 0.0  # seconds

    @property
    def artist_str(self) -> str:
        return ", ".join(self.artists)


def read_metadata(path: Path) -> Optional[AudioMetadata]:
    """
    Read metadata from an audio file using Mutagen.

    Args:
        path: Absolute path to the audio file.

    Returns:
        :class:`AudioMetadata` on success, ``None`` on failure.
    """
    try:
        from mutagen import File
        from mutagen.id3 import ID3NoHeaderError  # noqa: F401

        audio = File(path, easy=True)
        if audio is None:
            return None

        meta = AudioMetadata()

        meta.title = (audio.get("title", [""])[0] or "").strip()

        artists_raw = audio.get("artist", audio.get("artists", ["Unknown"]))
        meta.artists = [a.strip() for a in artists_raw if a.strip()]

        meta.album = (audio.get("album", [""])[0] or "").strip()
        meta.year  = ((audio.get("date", audio.get("year", [""]))[0]) or "")[:4]
        meta.genre = (audio.get("genre",  [""])[0] or "").strip()
        meta.isrc  = (audio.get("isrc",   [""])[0] or "").strip()

        tn = audio.get("tracknumber", ["0"])[0] or "0"
        try:
            meta.track_n = int(tn.split("/")[0])
        except (ValueError, IndexError):
            meta.track_n = 0

        if hasattr(audio, "info"):
            if hasattr(audio.info, "length"):
                meta.duration = audio.info.length
            if hasattr(audio.info, "bitrate"):
                meta.bitrate = audio.info.bitrate // 1000

        # Cover art — requires the non-easy interface.
        try:
            audio_full = File(path)
            if audio_full is not None and audio_full.tags:
                for tag in audio_full.tags.values():
                    if hasattr(tag, "data") and isinstance(tag.data, bytes):
                        meta.cover = tag.data
                        break
                    if hasattr(tag, "value") and isinstance(tag.value, bytes):
                        meta.cover = tag.value
                        break
        except Exception:
            pass

        return meta

    except Exception as exc:
        log.error(f"[MetadataReader] Error al leer {path}: {exc}")
        return None
