"""Unit tests for downloader.quality_manager."""
from __future__ import annotations

import pytest

from downloader.quality_manager import (
    DEFAULT_PROFILE,
    PROFILES,
    AudioFormat,
    AudioQuality,
    get_profile,
)


class TestGetProfile:
    @pytest.mark.parametrize("fmt,quality,expected_fmt,expected_q", [
        ("mp3",  "128k", AudioFormat.MP3,  AudioQuality.Q128),
        ("mp3",  "192k", AudioFormat.MP3,  AudioQuality.Q192),
        ("mp3",  "320k", AudioFormat.MP3,  AudioQuality.Q320),
        ("MP3",  "320K", AudioFormat.MP3,  AudioQuality.Q320),  # case-insensitive
        ("flac", "best", AudioFormat.FLAC, AudioQuality.BEST),
        ("flac", "ignored-for-lossless", AudioFormat.FLAC, AudioQuality.BEST),
        ("wav",  "best", AudioFormat.WAV,  AudioQuality.BEST),
        ("best", "best", AudioFormat.BEST, AudioQuality.BEST),
    ])
    def test_known(self, fmt, quality, expected_fmt, expected_q):
        p = get_profile(fmt, quality)
        assert p.format == expected_fmt
        assert p.quality == expected_q

    def test_unknown_falls_back_to_default(self):
        assert get_profile("xyz", "yyy") is DEFAULT_PROFILE
        assert get_profile("mp3", "999k") is DEFAULT_PROFILE

    def test_mp3_with_best_quality_returns_320(self):
        """User picks MP3 but with "best" quality → should use 320 (max MP3)."""
        p = get_profile("mp3", "best")
        assert p.format == AudioFormat.MP3
        assert p.quality == AudioQuality.Q320

    def test_default_is_best(self):
        """The default profile prefers original quality (no re-encoding)."""
        assert DEFAULT_PROFILE.format == AudioFormat.BEST


class TestPostprocessors:
    def test_mp3_returns_extract_audio(self):
        pp = get_profile("mp3", "320k").yt_dlp_postprocessors()
        assert len(pp) == 1
        assert pp[0]["key"] == "FFmpegExtractAudio"
        assert pp[0]["preferredcodec"] == "mp3"
        assert pp[0]["preferredquality"] == "320"  # 'k' stripped

    def test_flac_no_bitrate(self):
        pp = get_profile("flac", "best").yt_dlp_postprocessors()
        assert pp[0]["preferredcodec"] == "flac"
        assert "preferredquality" not in pp[0]

    def test_best_returns_empty(self):
        assert get_profile("best", "best").yt_dlp_postprocessors() == []

    def test_format_str_is_bestaudio(self):
        for profile in PROFILES.values():
            assert profile.yt_dlp_format_str() == "bestaudio/best"


class TestProfileImmutability:
    def test_is_frozen(self):
        p = get_profile("mp3", "320k")
        with pytest.raises(Exception):  # FrozenInstanceError
            p.label = "Modified"
