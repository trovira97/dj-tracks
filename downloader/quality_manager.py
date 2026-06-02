"""
downloader/quality_manager.py
==============================
Audio quality and format management for yt-dlp downloads.

Defines :class:`QualityProfile` and a set of pre-built profiles that map
user-facing choices (format + bitrate) to yt-dlp postprocessor options.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List


class AudioFormat(str, Enum):
    """Supported output container formats."""

    MP3  = "mp3"
    FLAC = "flac"
    WAV  = "wav"
    OGG  = "ogg"
    M4A  = "m4a"
    BEST = "best"   # Keep yt-dlp's native best format; no re-encode.


class AudioQuality(str, Enum):
    """MP3 VBR/CBR target bitrates (ignored for lossless formats)."""

    Q128 = "128k"
    Q192 = "192k"
    Q256 = "256k"
    Q320 = "320k"
    BEST = "best"


@dataclass(frozen=True)
class QualityProfile:
    """
    Immutable descriptor for a download quality preset.

    Attributes:
        format:  Target audio container / codec.
        quality: Bitrate hint (MP3 only; ignored for FLAC / WAV / best).
        label:   Human-readable name shown in the UI.
    """

    format:  AudioFormat
    quality: AudioQuality
    label:   str

    def yt_dlp_format_str(self) -> str:
        """
        Return the yt-dlp ``format`` selector string.

        Always requests the best available audio source; the actual
        transcoding is handled by :meth:`yt_dlp_postprocessors`.
        """
        return "bestaudio/best"

    def yt_dlp_postprocessors(self) -> List[Dict]:
        """
        Return the yt-dlp ``postprocessors`` list for this profile.

        For the ``BEST`` format no transcoding is applied; the native
        container is kept as-is (usually opus / webm / m4a).
        """
        if self.format == AudioFormat.BEST:
            return []

        pp: Dict = {
            "key":            "FFmpegExtractAudio",
            "preferredcodec": self.format.value,
        }

        if self.format == AudioFormat.MP3:
            # Strip the trailing 'k' so yt-dlp gets a plain integer.
            pp["preferredquality"] = self.quality.value.rstrip("k")

        return [pp]


# ─────────────────────────────────────────────────────────────────────────────
# Pre-built profiles
# ─────────────────────────────────────────────────────────────────────────────

PROFILES: Dict[str, QualityProfile] = {
    "mp3_128":  QualityProfile(AudioFormat.MP3,  AudioQuality.Q128,  "MP3  128 kbps"),
    "mp3_192":  QualityProfile(AudioFormat.MP3,  AudioQuality.Q192,  "MP3  192 kbps"),
    "mp3_320":  QualityProfile(AudioFormat.MP3,  AudioQuality.Q320,  "MP3  320 kbps"),
    "flac":     QualityProfile(AudioFormat.FLAC, AudioQuality.BEST,  "FLAC  Lossless"),
    "wav":      QualityProfile(AudioFormat.WAV,  AudioQuality.BEST,  "WAV   Lossless"),
    "best":     QualityProfile(AudioFormat.BEST, AudioQuality.BEST,  "Máxima calidad (original) ⭐"),
}

# Default to "best" so users get the original codec/bitrate from the source
# (FLAC from Bandcamp, opus-160 from YouTube Music, etc.) — no quality loss
# from a needless re-encode.
DEFAULT_PROFILE: QualityProfile = PROFILES["best"]


def get_profile(fmt: str, quality: str) -> QualityProfile:
    """
    Return the :class:`QualityProfile` matching *fmt* + *quality*.

    Falls back to :data:`DEFAULT_PROFILE` if no exact match is found.

    Examples::

        get_profile("mp3", "320k")  # → PROFILES["mp3_320"]
        get_profile("flac", "best") # → PROFILES["flac"]
        get_profile("wav", "anything") # → PROFILES["wav"]
    """
    fmt_lower = (fmt or "").lower()

    # Lossless / best formats ignore the quality token.
    if fmt_lower in ("flac", "wav", "best"):
        return PROFILES.get(fmt_lower, DEFAULT_PROFILE)

    # "best" or unrecognised quality on MP3 → use 320 (highest MP3).
    quality_lower = (quality or "").lower()
    if fmt_lower == "mp3" and quality_lower in ("best", ""):
        return PROFILES["mp3_320"]

    # MP3: build a key like "mp3_320" from "320k".
    bitrate = quality_lower.rstrip("k")
    key = f"{fmt_lower}_{bitrate}"
    return PROFILES.get(key, DEFAULT_PROFILE)
