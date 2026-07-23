"""Tests for the semver comparison + platform-asset picking in
``utils.app_updater``.

Regression guard for silent update failures: a semver bug that
mis-classifies "already newer" would either spam users with
false-positive update prompts, or worse, hide real updates.
"""
from __future__ import annotations

import sys
from unittest.mock import patch

from unittest.mock import MagicMock

import pytest

from utils.app_updater import (
    _parse_version,
    _pick_asset,
    apply_update,
    download_asset,
    is_frozen,
    is_newer,
)


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


# ─────────────────────────────────────────────────────────────────────────
# download_asset — streaming with progress
# ─────────────────────────────────────────────────────────────────────────

def _mock_streaming_response(chunks, content_length=None, ok=True):
    """Build a mocked requests.get response that behaves as a context
    manager and yields ``chunks`` from iter_content()."""
    r = MagicMock()
    r.__enter__ = MagicMock(return_value=r)
    r.__exit__  = MagicMock(return_value=False)
    if ok:
        r.raise_for_status = MagicMock()
    else:
        r.raise_for_status = MagicMock(side_effect=Exception("HTTP 5xx"))
    total = sum(len(c) for c in chunks if c) if content_length is None \
            else content_length
    r.headers = {"Content-Length": str(total)}
    r.iter_content = MagicMock(return_value=iter(chunks))
    return r


def test_download_asset_writes_bytes_to_disk(tmp_path):
    dest = tmp_path / "out.zip"
    resp = _mock_streaming_response([b"chunk-1-", b"chunk-2-", b"chunk-3"])
    with patch("requests.get", return_value=resp):
        assert download_asset("https://example.com/a.zip", dest) is True
    assert dest.read_bytes() == b"chunk-1-chunk-2-chunk-3"


def test_download_asset_calls_progress_callback(tmp_path):
    """Progress callback fires every chunk with (done_so_far, total)."""
    dest = tmp_path / "out.zip"
    chunks = [b"a" * 100, b"b" * 200, b"c" * 50]   # total 350 bytes
    resp = _mock_streaming_response(chunks)
    seen: list = []
    with patch("requests.get", return_value=resp):
        download_asset("https://x/a.zip", dest, progress=seen.append.__self__.append
                       if False else lambda done, total: seen.append((done, total)))
    # Three chunks → three progress updates.
    assert len(seen) == 3
    assert seen[0] == (100, 350)
    assert seen[1] == (300, 350)
    assert seen[2] == (350, 350)


def test_download_asset_skips_empty_chunks(tmp_path):
    """iter_content can yield b'' at connection boundaries — must be skipped."""
    dest = tmp_path / "out.zip"
    chunks = [b"real", b"", b"more"]
    resp = _mock_streaming_response(chunks)
    with patch("requests.get", return_value=resp):
        download_asset("https://x/a.zip", dest)
    assert dest.read_bytes() == b"realmore"


def test_download_asset_returns_false_on_http_error(tmp_path):
    dest = tmp_path / "out.zip"
    resp = _mock_streaming_response([], ok=False)
    with patch("requests.get", return_value=resp):
        assert download_asset("https://x/a.zip", dest) is False


def test_download_asset_deletes_dest_on_failure(tmp_path):
    """Partial download → delete the incomplete file so a retry doesn't
    fail its integrity check."""
    dest = tmp_path / "out.zip"
    dest.write_bytes(b"stale content")
    with patch("requests.get", side_effect=RuntimeError("network drop")):
        download_asset("https://x/a.zip", dest)
    assert not dest.exists()


def test_download_asset_progress_exception_does_not_break_download(tmp_path):
    """A badly-written progress callback must not abort the download."""
    dest = tmp_path / "out.zip"
    chunks = [b"chunk1", b"chunk2"]
    resp = _mock_streaming_response(chunks)
    def bad_progress(done, total):
        raise RuntimeError("UI thread died")
    with patch("requests.get", return_value=resp):
        assert download_asset("https://x/a.zip", dest,
                               progress=bad_progress) is True
    assert dest.read_bytes() == b"chunk1chunk2"


def test_download_asset_no_content_length_still_works(tmp_path):
    """Some CDNs (chunked-transfer) don't send Content-Length — total=0,
    progress callback still fires with done bytes."""
    dest = tmp_path / "out.zip"
    r = MagicMock()
    r.__enter__ = MagicMock(return_value=r)
    r.__exit__  = MagicMock(return_value=False)
    r.raise_for_status = MagicMock()
    r.headers = {}     # no Content-Length
    r.iter_content = MagicMock(return_value=iter([b"data"]))
    seen: list = []
    with patch("requests.get", return_value=r):
        download_asset("https://x/a.zip", dest,
                        progress=lambda d, t: seen.append((d, t)))
    assert seen == [(4, 0)]


def test_download_asset_respects_custom_chunk_size(tmp_path):
    """The chunk_size kwarg is passed through to iter_content."""
    dest = tmp_path / "out.zip"
    resp = _mock_streaming_response([b"x"])
    with patch("requests.get", return_value=resp):
        download_asset("https://x/a.zip", dest, chunk_size=4096)
    resp.iter_content.assert_called_once_with(chunk_size=4096)


# ─────────────────────────────────────────────────────────────────────────
# is_frozen
# ─────────────────────────────────────────────────────────────────────────

def test_is_frozen_false_in_source_mode():
    """Running from source (as tests do) — sys.frozen is unset."""
    # Ensure we're testing the real behaviour: no artificial sys.frozen.
    with patch.object(sys, "frozen", False, create=True):
        assert is_frozen() is False


def test_is_frozen_true_when_pyinstaller_marker_set():
    with patch.object(sys, "frozen", True, create=True):
        assert is_frozen() is True


# ─────────────────────────────────────────────────────────────────────────
# apply_update — safety guards + dispatch
# ─────────────────────────────────────────────────────────────────────────

def test_apply_update_refuses_when_not_frozen(tmp_path):
    """Never rewrite bytes over a dev-source install."""
    asset = tmp_path / "new.zip"
    asset.write_bytes(b"x")
    with patch("utils.app_updater.is_frozen", return_value=False):
        assert apply_update(asset) is False


def test_apply_update_refuses_on_non_windows(tmp_path):
    """The swap logic uses robocopy + .bat — Windows only for now."""
    asset = tmp_path / "new.zip"
    asset.write_bytes(b"x")
    with patch("utils.app_updater.is_frozen", return_value=True), \
         patch.object(sys, "platform", "darwin"):
        assert apply_update(asset) is False


def test_apply_update_refuses_when_asset_missing(tmp_path):
    """The downloader may have deleted the file after a failure — never
    proceed with the swap when the source doesn't exist."""
    ghost = tmp_path / "does-not-exist.exe"
    with patch("utils.app_updater.is_frozen", return_value=True), \
         patch.object(sys, "platform", "win32"):
        assert apply_update(ghost) is False


def test_apply_update_refuses_unsupported_asset_type(tmp_path):
    """We only know how to swap .exe (onefile) and .zip (onedir)."""
    weird = tmp_path / "asset.tar.gz"
    weird.write_bytes(b"x")
    with patch("utils.app_updater.is_frozen", return_value=True), \
         patch.object(sys, "platform", "win32"), \
         patch.object(sys, "executable", str(tmp_path / "DJ Tracks.exe")):
        assert apply_update(weird) is False


def test_apply_update_dispatches_exe_to_exe_swap(tmp_path):
    """A .exe asset routes through _apply_exe_swap."""
    new_exe = tmp_path / "new.exe"
    new_exe.write_bytes(b"x")
    current  = tmp_path / "DJ Tracks.exe"
    current.write_bytes(b"old")
    with patch("utils.app_updater.is_frozen", return_value=True), \
         patch.object(sys, "platform", "win32"), \
         patch.object(sys, "executable", str(current)), \
         patch("utils.app_updater._apply_exe_swap",
               return_value=True) as swap, \
         patch("threading.Thread"):        # avoid the os._exit trampoline
        assert apply_update(new_exe) is True
    swap.assert_called_once()


def test_apply_update_dispatches_zip_to_zip_swap(tmp_path):
    new_zip = tmp_path / "new.zip"
    new_zip.write_bytes(b"x")
    current = tmp_path / "DJ Tracks.exe"
    current.write_bytes(b"old")
    with patch("utils.app_updater.is_frozen", return_value=True), \
         patch.object(sys, "platform", "win32"), \
         patch.object(sys, "executable", str(current)), \
         patch("utils.app_updater._apply_zip_swap",
               return_value=True) as swap, \
         patch("threading.Thread"):
        assert apply_update(new_zip) is True
    swap.assert_called_once()


def test_apply_update_returns_false_when_swap_fails(tmp_path):
    """When the swap helper reports failure, don't schedule the exit."""
    new_exe = tmp_path / "new.exe"
    new_exe.write_bytes(b"x")
    current = tmp_path / "DJ Tracks.exe"
    current.write_bytes(b"old")
    with patch("utils.app_updater.is_frozen", return_value=True), \
         patch.object(sys, "platform", "win32"), \
         patch.object(sys, "executable", str(current)), \
         patch("utils.app_updater._apply_exe_swap",
               return_value=False), \
         patch("threading.Thread") as thread_ctor:
        assert apply_update(new_exe) is False
    # Exit trampoline must NOT have been scheduled on failure.
    thread_ctor.assert_not_called()
