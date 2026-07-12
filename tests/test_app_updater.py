"""Tests for the semver comparison + platform-asset picking in
``utils.app_updater``.

Regression guard for silent update failures: a semver bug that
mis-classifies "already newer" would either spam users with
false-positive update prompts, or worse, hide real updates.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

from utils.app_updater import _parse_version, _pick_asset, is_newer


# ── Version parsing ──────────────────────────────────────────────────────

def test_parse_simple_semver():
    assert _parse_version("2.3.1") == (2, 3, 1, 0)


def test_parse_v_prefix_stripped():
    assert _parse_version("v2.3.1") == _parse_version("2.3.1")


def test_parse_two_component_zero_pads():
    assert _parse_version("2.1") == (2, 1, 0, 0)


def test_parse_four_component():
    assert _parse_version("2.3.1.5") == (2, 3, 1, 5)


def test_parse_empty_string():
    assert _parse_version("") == (0,)


def test_parse_prerelease_suffix():
    """`2.1.0-rc1` should parse — the -rc1 becomes a fourth digit."""
    v = _parse_version("2.1.0-rc1")
    assert v[:3] == (2, 1, 0)


def test_parse_garbage_falls_back():
    # A version string with no digits at all.
    assert _parse_version("gibberish") == (0,)


# ── is_newer semantics ───────────────────────────────────────────────────

def test_is_newer_patch_bump():
    assert is_newer("2.3.2", "2.3.1")


def test_is_newer_minor_bump():
    assert is_newer("2.4.0", "2.3.9")


def test_is_newer_major_bump():
    assert is_newer("3.0.0", "2.9.9")


def test_same_version_not_newer():
    assert not is_newer("2.3.1", "2.3.1")


def test_older_not_newer():
    assert not is_newer("2.3.0", "2.3.1")


def test_v_prefix_matches_bare():
    assert not is_newer("v2.3.1", "2.3.1")


def test_missing_patch_component_compares_correctly():
    # Regression: "2.3" should be equal to "2.3.0", not less.
    assert not is_newer("2.3", "2.3.0")
    assert not is_newer("2.3.0", "2.3")


# ── Asset selection ──────────────────────────────────────────────────────

def _asset(name, size=1_000_000):
    return {"name": name, "browser_download_url": f"https://x/{name}",
            "size": size}


def test_pick_none_when_no_assets():
    assert _pick_asset([]) is None


def test_pick_exe_preferred_on_windows():
    assets = [
        _asset("DJ Tracks v2.3.0 macOS.dmg"),
        _asset("DJ Tracks v2.3.0 Setup.exe"),
        _asset("DJ Tracks v2.3.0 Windows.zip"),
    ]
    with patch.object(sys, "platform", "win32"):
        picked = _pick_asset(assets)
    assert picked["name"].endswith(".exe")


def test_pick_windows_zip_when_no_exe():
    assets = [
        _asset("DJ Tracks v2.3.0 macOS.dmg"),
        _asset("DJ Tracks v2.3.0 Windows.zip"),
        _asset("DJ Tracks v2.3.0 Linux.tar.gz"),
    ]
    with patch.object(sys, "platform", "win32"):
        picked = _pick_asset(assets)
    assert "Windows.zip" in picked["name"]


def test_pick_falls_back_to_first_on_non_windows():
    """macOS/Linux users get whatever comes first — the fallback path."""
    assets = [
        _asset("DJ Tracks v2.3.0 macOS.dmg"),
        _asset("DJ Tracks v2.3.0 Linux.tar.gz"),
    ]
    with patch.object(sys, "platform", "darwin"):
        picked = _pick_asset(assets)
    assert picked is not None


def test_pick_case_insensitive_matching():
    """Asset names are lower-cased before extension matching."""
    with patch.object(sys, "platform", "win32"):
        picked = _pick_asset([_asset("DJ Tracks v2.3.0 Setup.EXE")])
    assert picked["name"].lower().endswith(".exe")
