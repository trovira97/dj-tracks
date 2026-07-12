"""Tests for the pure logic in ``downloader.audio_downloader``.

Covers the parts that are testable without actually invoking yt-dlp
or spotdl:

- Error classifiers (7 predicates: drm / geo / age / private / premium /
  not_found / irrecoverable) — including the multi-branch ``is_drm_error``
- ``_humanise_error`` — raw traceback → short Spanish user message
- ``_build_yt_query`` — search query composition
- ``DownloadTask.display_name`` — presentation property

The download flow itself (``download``, ``_download_ytdlp``,
``_download_spotdl``) is not covered here — those require an actual
network + ffmpeg and are validated by manual end-to-end runs.
"""
from __future__ import annotations

import pytest

from downloader.audio_downloader import (
    AudioDownloader,
    DownloadStatus,
    DownloadTask,
)
from providers import TrackInfo

_AD = AudioDownloader


# ─────────────────────────────────────────────────────────────────────────
# is_not_found_error / is_irrecoverable_error
# ─────────────────────────────────────────────────────────────────────────

def test_soundcloud_404_is_irrecoverable():
    """Regression guard: 404s must trigger cross-platform retry."""
    raw = "ERROR: unable to download webpage: HTTP Error 404: Not Found"
    assert _AD.is_not_found_error(raw)
    assert _AD.is_irrecoverable_error(raw)


def test_youtube_not_found_is_irrecoverable():
    assert _AD.is_irrecoverable_error(
        "ERROR: Video not found — content may have been removed")


def test_generic_not_found_lowercase_matches():
    assert _AD.is_not_found_error("Content not found on remote")


# ─────────────────────────────────────────────────────────────────────────
# 403 / network — must remain RECOVERABLE
# ─────────────────────────────────────────────────────────────────────────

def test_403_stays_recoverable():
    """403 usually means stale yt-dlp or rate limit — retrying the same
    source (or updating yt-dlp) resolves it, not switching platforms."""
    assert not _AD.is_irrecoverable_error("ERROR: HTTP Error 403: Forbidden")


def test_network_timeout_stays_recoverable():
    assert not _AD.is_irrecoverable_error("ERROR: The read operation timed out")


def test_generic_connection_error_stays_recoverable():
    assert not _AD.is_irrecoverable_error("ERROR: connection reset by peer")


# ─────────────────────────────────────────────────────────────────────────
# is_drm_error — three-branch classifier
# ─────────────────────────────────────────────────────────────────────────

def test_drm_keyword_match():
    """Branch 1: explicit 'drm' keyword."""
    assert _AD.is_drm_error("ERROR: DRM-protected content, cannot download")


@pytest.mark.parametrize("marker", [
    "not currently available",
    "not available in your country",
    "sign in to download",
    "preview is not available",
    "requires authentication",
    "track is not available for streaming",
])
def test_drm_soundcloud_markers(marker):
    """Branch 2: SoundCloud-specific error phrases."""
    assert _AD.is_drm_error(f"ERROR: {marker}")


def test_drm_hls_encrypted_403_matches():
    """Branch 3: HLS + AES + 403 — encrypted stream we can't decrypt."""
    assert _AD.is_drm_error(
        "ERROR: hls: unable to fetch key: HTTP Error 403: Forbidden AES")


def test_drm_hls_alone_does_not_match():
    """HLS mentioned without encryption/failure signals is not DRM."""
    assert not _AD.is_drm_error("Downloading HLS playlist manifest")


def test_drm_empty_input():
    assert not _AD.is_drm_error("")


# ─────────────────────────────────────────────────────────────────────────
# is_geo_error / is_age_error / is_private_error / is_premium_error
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "ERROR: this video is not available in your country",
    "ERROR: geo-restricted content",
    "This video is geo-blocked in your region",
    "This content has been blocked it on copyright grounds",
])
def test_geo_error_variants(raw):
    assert _AD.is_geo_error(raw)


def test_geo_error_negative():
    assert not _AD.is_geo_error("This video is DRM-protected")


@pytest.mark.parametrize("raw", [
    "Sign in to confirm your age",
    "This video is age-restricted",
    "age restricted content",
    "This video may be inappropriate for some users",
])
def test_age_error_variants(raw):
    assert _AD.is_age_error(raw)


@pytest.mark.parametrize("raw", [
    "Private video",
    "This video is private, sign in to view",
    "Video unavailable — this is a private video",
])
def test_private_error_variants(raw):
    assert _AD.is_private_error(raw)


@pytest.mark.parametrize("raw", [
    "This channel is members-only",
    "Members only content",
    "This is a Premium video",
    "This video is for subscribers only",
])
def test_premium_error_variants(raw):
    assert _AD.is_premium_error(raw)


# ─────────────────────────────────────────────────────────────────────────
# is_irrecoverable_error — full aggregate coverage
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw", [
    "ERROR: DRM-protected",
    "ERROR: sign in to download this track",
    "ERROR: geo-restricted content",
    "Sign in to confirm your age",
    "Private video",
    "members-only video",
    "HTTP Error 404: Not Found",
])
def test_all_irrecoverable_families(raw):
    assert _AD.is_irrecoverable_error(raw)


def test_success_output_not_flagged_as_error():
    assert not _AD.is_irrecoverable_error(
        "[download] 100% of 4.2MiB in 00:03")


def test_empty_input_is_not_irrecoverable():
    assert not _AD.is_irrecoverable_error("")


# ─────────────────────────────────────────────────────────────────────────
# _humanise_error — raw → Spanish user-facing string
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected_snippet", [
    # Class-based dispatch (order matters — DRM checked before 403/404)
    ("ERROR: DRM-protected content",           "Audio protegido"),
    ("ERROR: sign in to download this track",  "Audio protegido"),
    ("ERROR: geo-restricted content",          "región"),
    ("ERROR: age-restricted video",            "restricción de edad"),
    ("ERROR: Private video",                   "privado"),
    ("ERROR: members-only video",              "premium"),
    # HTTP status codes
    ("ERROR: HTTP Error 403: Forbidden",       "403"),
    ("ERROR: HTTP Error 404: Not Found",       "404"),
    ("ERROR: HTTP Error 429: Too Many Requests", "Rate limit"),
    # Local/system errors
    ("ffmpeg: could not encode",               "ffmpeg"),
    ("[Errno 13] Permission denied: 'out.mp3'","escritura"),
    ("network is unreachable",                 "red"),
    ("connection timed out",                   "red"),
])
def test_humanise_error_mapping(raw, expected_snippet):
    msg = _AD._humanise_error(raw)
    assert expected_snippet.lower() in msg.lower(), (
        f"Expected {expected_snippet!r} in humanised error for {raw!r}, "
        f"got {msg!r}"
    )


def test_humanise_unknown_error_returns_last_line():
    """Fallback: unknown error → last non-empty line, truncated to 140 chars."""
    raw = "Traceback (most recent call last):\n  File ...\nWeirdError: xyz"
    assert _AD._humanise_error(raw) == "WeirdError: xyz"


def test_humanise_empty_error_returns_placeholder():
    assert _AD._humanise_error("") == "Error desconocido"


def test_humanise_truncates_long_last_line():
    raw = "X" * 200
    assert len(_AD._humanise_error(raw)) == 140


# ─────────────────────────────────────────────────────────────────────────
# _build_yt_query — search query composition
# ─────────────────────────────────────────────────────────────────────────

def test_build_yt_query_composes_artist_title_official():
    """The 'official audio' suffix keeps yt-dlp away from fan videos,
    lyrics karaokes and live versions."""
    track = TrackInfo(title="Get Lucky", artists=["Daft Punk"])
    dl = _AD.__new__(_AD)   # avoid __init__ (no filesystem)
    assert dl._build_yt_query(track) == "Daft Punk Get Lucky official audio"


def test_build_yt_query_joins_multiple_artists():
    track = TrackInfo(title="Track", artists=["Artist A", "Artist B"])
    dl = _AD.__new__(_AD)
    q = dl._build_yt_query(track)
    assert "Artist A" in q and "Artist B" in q and "Track" in q


# ─────────────────────────────────────────────────────────────────────────
# DownloadTask.display_name
# ─────────────────────────────────────────────────────────────────────────

def _track(**kw):
    kw.setdefault("title", "Song")
    kw.setdefault("artists", ["Artist"])
    return TrackInfo(**kw)


def test_display_name_format():
    from downloader.quality_manager import get_profile
    profile = get_profile("mp3", "320")
    task = DownloadTask(track=_track(title="Get Lucky", artists=["Daft Punk"]),
                        profile=profile, output_dir=".")
    assert task.display_name == "Daft Punk — Get Lucky"


def test_display_name_multiple_artists():
    from downloader.quality_manager import get_profile
    profile = get_profile("mp3", "320")
    task = DownloadTask(track=_track(artists=["A", "B"], title="T"),
                        profile=profile, output_dir=".")
    assert task.display_name == "A, B — T"


def test_download_task_defaults():
    """Fresh tasks start in PENDING, progress 0, no output path."""
    from downloader.quality_manager import get_profile
    profile = get_profile("mp3", "320")
    task = DownloadTask(track=_track(), profile=profile,
                        output_dir="/tmp/x")
    assert task.status == DownloadStatus.PENDING
    assert task.progress == 0.0
    assert task.output_path is None
    assert task.error_msg == ""
    assert task.task_id  # generated via uuid4


def test_download_task_id_is_unique():
    from downloader.quality_manager import get_profile
    profile = get_profile("mp3", "320")
    ids = {
        DownloadTask(track=_track(), profile=profile,
                     output_dir=".").task_id
        for _ in range(50)
    }
    assert len(ids) == 50
