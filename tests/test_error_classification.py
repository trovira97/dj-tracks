"""Tests for AudioDownloader error classifiers — especially the
cross-platform-retry gate ``is_irrecoverable_error``.

Regression guard for the bug where SoundCloud 404s ("track removed")
never triggered the cross-platform retry, leaving the download in a
permanent-error state instead of falling back to YouTube / Apple Music.
"""
from __future__ import annotations

from downloader.audio_downloader import AudioDownloader


# ── 404 / not-found — must be irrecoverable so cross-platform kicks in ────

def test_soundcloud_404_is_irrecoverable():
    raw = "ERROR: unable to download webpage: HTTP Error 404: Not Found"
    assert AudioDownloader.is_not_found_error(raw)
    assert AudioDownloader.is_irrecoverable_error(raw), (
        "404 must trigger cross-platform retry — a removed SoundCloud "
        "track will never come back on the same URL."
    )


def test_youtube_not_found_is_irrecoverable():
    raw = "ERROR: Video not found — content may have been removed"
    assert AudioDownloader.is_irrecoverable_error(raw)


def test_generic_not_found_lowercase_matches():
    assert AudioDownloader.is_not_found_error("Content not found on remote")


# ── 403 / network — must remain RECOVERABLE (retry same source) ───────────

def test_403_stays_recoverable():
    """403 usually means stale yt-dlp or rate limit — retrying the same
    source (or updating yt-dlp) resolves it, not switching platforms."""
    raw = "ERROR: HTTP Error 403: Forbidden"
    assert not AudioDownloader.is_irrecoverable_error(raw)


def test_network_timeout_stays_recoverable():
    raw = "ERROR: The read operation timed out"
    assert not AudioDownloader.is_irrecoverable_error(raw)


def test_generic_connection_error_stays_recoverable():
    raw = "ERROR: connection reset by peer"
    assert not AudioDownloader.is_irrecoverable_error(raw)


# ── Existing irrecoverable classes still classified correctly ─────────────

def test_drm_is_irrecoverable():
    raw = "ERROR: This track is not currently available"
    assert AudioDownloader.is_irrecoverable_error(raw)


def test_private_video_is_irrecoverable():
    raw = "ERROR: this video is private and cannot be downloaded"
    assert AudioDownloader.is_irrecoverable_error(raw)


def test_geo_block_is_irrecoverable():
    raw = "ERROR: This video is not available in your country"
    assert AudioDownloader.is_irrecoverable_error(raw)


# ── Empty / benign inputs ─────────────────────────────────────────────────

def test_empty_raw_is_not_error():
    assert not AudioDownloader.is_not_found_error("")
    assert not AudioDownloader.is_irrecoverable_error("")


def test_success_message_is_not_error():
    assert not AudioDownloader.is_irrecoverable_error(
        "Downloading video 1 of 1... 100% complete"
    )
