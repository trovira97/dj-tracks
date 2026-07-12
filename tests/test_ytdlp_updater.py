"""Tests for the extracted yt-dlp updater helper.

The updater is the recommended fix for the majority of "HTTP 403 /
video unavailable" download failures — YouTube changes its bot
protection every few months and yt-dlp ships patches fast.  These
tests protect the version-normalisation and status-classification
logic (the actual pip subprocess is patched out so nothing installs
during a test run).
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from utils.ytdlp_updater import _norm, update_ytdlp


# ── Version normalisation ────────────────────────────────────────────────

def test_norm_strips_leading_zeroes():
    """PyPI 2026.6.9 vs yt-dlp 2026.06.09 must compare equal."""
    assert _norm("2026.6.9") == _norm("2026.06.09")


def test_norm_handles_dashes():
    assert _norm("2026.6-9") == _norm("2026.6.9")


def test_norm_keeps_non_numeric_as_strings():
    v = _norm("2026.6.9-rc1")
    assert v[:3] == (2026, 6, 9)
    assert v[3] == "rc1"


def test_norm_empty_string():
    # Empty string yields a single empty-string element — harmless.
    v = _norm("")
    assert v == ("",)


# ── Status classification ────────────────────────────────────────────────

def _patch_yt_dlp(version: str):
    """Insert a fake yt_dlp module into sys.modules for the duration
    of the calling test.  Returns the patcher context manager."""
    fake = SimpleNamespace(version=SimpleNamespace(__version__=version))
    return patch.dict("sys.modules", {"yt_dlp": fake})


def _patch_pypi_response(version: str):
    """Patch requests.get to return a fake PyPI JSON body."""
    fake_resp = MagicMock()
    fake_resp.raise_for_status = MagicMock()
    fake_resp.json.return_value = {"info": {"version": version}}
    return patch("requests.get", return_value=fake_resp)


def test_up_to_date_reports_no_upgrade():
    """Same version on PyPI → status='up-to-date', no subprocess spawn."""
    with _patch_yt_dlp("2026.06.09"), \
         _patch_pypi_response("2026.6.9"), \
         patch("subprocess.Popen") as popen:
        r = update_ytdlp()
    assert r["status"] == "up-to-date"
    assert r["current"] == "2026.06.09"
    assert r["latest"] == "2026.6.9"
    popen.assert_not_called()


def test_newer_pypi_triggers_upgrade_subprocess():
    with _patch_yt_dlp("2026.6.9"), \
         _patch_pypi_response("2026.7.1"), \
         patch("subprocess.Popen") as popen:
        r = update_ytdlp()
    assert r["status"] == "updated"
    assert r["current"] == "2026.6.9"
    assert r["latest"] == "2026.7.1"
    popen.assert_called_once()
    # Command line must invoke pip install --upgrade yt-dlp.
    args = popen.call_args[0][0]
    assert "pip" in args
    assert "install" in args
    assert "--upgrade" in args
    assert "yt-dlp" in args


def test_yt_dlp_import_failure_returns_error():
    """If yt_dlp itself is broken, report cleanly instead of raising."""
    with patch.dict("sys.modules", {"yt_dlp": None}), \
         patch("subprocess.Popen") as popen:
        # sys.modules[X] = None makes import raise ImportError.
        r = update_ytdlp()
    assert r["status"] == "error"
    assert r["current"] == "?"
    popen.assert_not_called()


def test_pypi_unreachable_returns_error():
    """When PyPI is down we still return a structured dict — no crash."""
    with _patch_yt_dlp("2026.6.9"), \
         patch("requests.get", side_effect=Exception("network down")), \
         patch("subprocess.Popen") as popen:
        r = update_ytdlp()
    assert r["status"] == "error"
    assert r["current"] == "2026.6.9"
    assert r["latest"] == "?"
    assert "PyPI" in r["message"]
    popen.assert_not_called()


def test_subprocess_launch_failure_returns_error():
    """If Popen itself fails (e.g. no permission to fork), still don't
    raise up to the UI callback."""
    with _patch_yt_dlp("2026.6.9"), \
         _patch_pypi_response("2026.7.1"), \
         patch("subprocess.Popen", side_effect=OSError("permission denied")):
        r = update_ytdlp()
    assert r["status"] == "error"
    assert "instalador" in r["message"]
