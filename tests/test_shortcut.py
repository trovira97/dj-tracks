"""Tests for ``utils.shortcut`` — cross-platform desktop launcher creator.

Tests cover the pure path helpers, the platform-specific file-content
generators (macOS .command, Linux .desktop) running against tmp_path,
and the dispatcher.  The Windows PowerShell path mocks subprocess
since real .lnk creation requires COM.

Focus:
- ``_project_root`` — source vs frozen bundle
- ``_icon_path`` / ``_logo_path`` — exists / missing
- ``_windows_desktop`` — winreg hit, winreg miss, fallback to ~/Desktop
- ``_linux_desktop`` — XDG config parsing + locale-named folders
- ``_create_macos`` — .command script content + chmod
- ``_create_linux`` — .desktop content, XDG vs ~/.local fallback
- ``_create_windows`` — PowerShell invocation + error path
- ``create_shortcut`` — platform dispatcher
"""
from __future__ import annotations

import os
import stat
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from utils import shortcut
from utils.shortcut import (
    _create_linux,
    _create_macos,
    _icon_path,
    _linux_desktop,
    _logo_path,
    _project_root,
    create_shortcut,
)


# ─────────────────────────────────────────────────────────────────────────
# _project_root
# ─────────────────────────────────────────────────────────────────────────

def test_project_root_source_mode():
    """Source mode: resolves to the repo root (parent of utils/)."""
    with patch.object(sys, "frozen", False, create=True):
        root = _project_root()
    assert (root / "utils" / "shortcut.py").exists()


def test_project_root_frozen_mode(tmp_path):
    """Frozen mode: returns the directory holding the executable."""
    fake_exe = tmp_path / "DJ Tracks.exe"
    fake_exe.write_bytes(b"x")
    with patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", str(fake_exe)):
        assert _project_root() == tmp_path


# ─────────────────────────────────────────────────────────────────────────
# _icon_path / _logo_path
# ─────────────────────────────────────────────────────────────────────────

def test_icon_path_returns_path_when_exists(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "icon.ico").write_bytes(b"ico")
    with patch("utils.shortcut._project_root", return_value=tmp_path):
        assert _icon_path() == tmp_path / "assets" / "icon.ico"


def test_icon_path_returns_none_when_missing(tmp_path):
    """No assets/icon.ico on disk → None (don't fabricate a path)."""
    with patch("utils.shortcut._project_root", return_value=tmp_path):
        assert _icon_path() is None


def test_logo_path_returns_path_when_exists(tmp_path):
    (tmp_path / "assets").mkdir()
    (tmp_path / "assets" / "logo.png").write_bytes(b"png")
    with patch("utils.shortcut._project_root", return_value=tmp_path):
        assert _logo_path() == tmp_path / "assets" / "logo.png"


def test_logo_path_returns_none_when_missing(tmp_path):
    with patch("utils.shortcut._project_root", return_value=tmp_path):
        assert _logo_path() is None


# ─────────────────────────────────────────────────────────────────────────
# _windows_desktop  (winreg path — Windows-only import)
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.skipif(sys.platform != "win32", reason="winreg requires Windows")
def test_windows_desktop_falls_back_when_registry_fails():
    """If winreg lookup raises, we fall back to ~/Desktop — never crash."""
    with patch("winreg.OpenKey", side_effect=OSError("registry locked")):
        assert shortcut._windows_desktop() == Path.home() / "Desktop"


@pytest.mark.skipif(sys.platform != "win32", reason="winreg requires Windows")
def test_windows_desktop_falls_back_when_registry_returns_bad_path(tmp_path):
    """Registry returns a path that doesn't exist → fall back to ~/Desktop
    rather than return a stale location."""
    bad_handle = MagicMock()
    bad_handle.__enter__ = MagicMock(return_value=bad_handle)
    bad_handle.__exit__  = MagicMock(return_value=False)
    with patch("winreg.OpenKey", return_value=bad_handle), \
         patch("winreg.QueryValueEx",
               return_value=(str(tmp_path / "nonexistent"), 1)):
        assert shortcut._windows_desktop() == Path.home() / "Desktop"


# ─────────────────────────────────────────────────────────────────────────
# _linux_desktop
# ─────────────────────────────────────────────────────────────────────────

def test_linux_desktop_reads_xdg_config(tmp_path, monkeypatch):
    """When ~/.config/user-dirs.dirs sets XDG_DESKTOP_DIR, respect it."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".config"
    cfg.mkdir()
    desk = tmp_path / "MyDesktop"
    desk.mkdir()
    (cfg / "user-dirs.dirs").write_text(
        f'XDG_DESKTOP_DIR="{desk}"\n', encoding="utf-8")
    assert _linux_desktop() == desk


def test_linux_desktop_expands_home_variable(tmp_path, monkeypatch):
    """XDG config uses literal '$HOME' prefix — must be expanded."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    cfg = tmp_path / ".config"
    cfg.mkdir()
    desk = tmp_path / "Workspace"
    desk.mkdir()
    (cfg / "user-dirs.dirs").write_text(
        'XDG_DESKTOP_DIR="$HOME/Workspace"\n', encoding="utf-8")
    assert _linux_desktop() == desk


def test_linux_desktop_falls_back_to_locale_names(tmp_path, monkeypatch):
    """No XDG config → check common locale-named folders (Escritorio,
    Bureau, Schreibtisch, etc.)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    (tmp_path / "Escritorio").mkdir()   # Spanish locale fallback
    assert _linux_desktop() == tmp_path / "Escritorio"


def test_linux_desktop_returns_none_when_nothing_found(tmp_path, monkeypatch):
    """No XDG config, no locale folder → None (caller falls back to
    ~/.local/share/applications)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    assert _linux_desktop() is None


# ─────────────────────────────────────────────────────────────────────────
# _create_macos
# ─────────────────────────────────────────────────────────────────────────

def test_create_macos_source_mode(tmp_path, monkeypatch):
    """Source: writes a bash script that cd's to repo + runs main.py."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path / "repo"), \
         patch.object(sys, "frozen", False, create=True), \
         patch.object(sys, "executable", "/usr/bin/python3"):
        target = _create_macos()
    assert target == tmp_path / "Desktop" / "DJ Tracks.command"
    content = target.read_text(encoding="utf-8")
    assert content.startswith("#!/bin/bash")
    assert "main.py" in content
    assert "/usr/bin/python3" in content


def test_create_macos_frozen_mode(tmp_path, monkeypatch):
    """Frozen: just cd + run the bundled .app binary (no main.py)."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path / "app"), \
         patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable",
                      "/Apps/DJ Tracks.app/Contents/MacOS/DJ Tracks"):
        target = _create_macos()
    content = target.read_text(encoding="utf-8")
    assert "main.py" not in content   # no script arg when frozen


def test_create_macos_is_executable(tmp_path, monkeypatch):
    """chmod 0o755 must be applied so Finder double-click runs it."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path):
        target = _create_macos()
    mode = os.stat(target).st_mode
    # Owner execute bit must be set (on Windows chmod is a no-op but
    # the call must still succeed — we just skip the check there).
    if sys.platform != "win32":
        assert mode & stat.S_IXUSR


def test_create_macos_creates_desktop_dir_when_missing(tmp_path, monkeypatch):
    """A fresh user with no ~/Desktop still gets a shortcut — mkdir
    handles the creation."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    # Desktop doesn't exist yet.
    assert not (tmp_path / "Desktop").exists()
    with patch("utils.shortcut._project_root", return_value=tmp_path):
        _create_macos()
    assert (tmp_path / "Desktop").is_dir()


# ─────────────────────────────────────────────────────────────────────────
# _create_linux
# ─────────────────────────────────────────────────────────────────────────

def test_create_linux_writes_desktop_entry_to_xdg_desktop(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    desk = tmp_path / "Desktop"
    desk.mkdir()
    (tmp_path / ".config").mkdir()
    (tmp_path / ".config" / "user-dirs.dirs").write_text(
        f'XDG_DESKTOP_DIR="{desk}"\n', encoding="utf-8")

    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", False, create=True), \
         patch.object(sys, "executable", "/usr/bin/python3"), \
         patch("subprocess.run"):           # suppress the `gio` call
        target = _create_linux()

    assert target == desk / "DJ Tracks.desktop"
    content = target.read_text(encoding="utf-8")
    assert "[Desktop Entry]" in content
    assert "Name=DJ Tracks" in content
    assert "Type=Application" in content
    assert "Categories=Music;AudioVideo;" in content
    assert "/usr/bin/python3" in content
    assert "main.py" in content


def test_create_linux_falls_back_to_applications_dir(tmp_path, monkeypatch):
    """No desktop folder found → write into ~/.local/share/applications
    so GNOME/KDE still show the launcher in the app grid."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", False, create=True), \
         patch("subprocess.run"):
        target = _create_linux()
    expected = tmp_path / ".local" / "share" / "applications" / "DJ Tracks.desktop"
    assert target == expected
    assert expected.exists()


def test_create_linux_frozen_exec_line(tmp_path, monkeypatch):
    """Frozen build: Exec is just the executable, no `python main.py`."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", True, create=True), \
         patch.object(sys, "executable", "/opt/djtracks/DJ Tracks"), \
         patch("subprocess.run"):
        target = _create_linux()
    content = target.read_text(encoding="utf-8")
    # Path separators vary across platforms (Path(exe) normalises on Windows);
    # just confirm the executable name is on an Exec= line and no main.py.
    exec_lines = [l for l in content.splitlines() if l.startswith("Exec=")]
    assert len(exec_lines) == 1
    assert "DJ Tracks" in exec_lines[0]
    assert "main.py" not in content


def test_create_linux_marks_trusted_via_gio(tmp_path, monkeypatch):
    """Best-effort GNOME trust via `gio set ... metadata::trusted true`."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", False, create=True), \
         patch("subprocess.run") as run:
        _create_linux()
    assert run.called
    all_args = " ".join(str(c) for c in run.call_args_list)
    assert "gio" in all_args
    assert "trusted" in all_args


def test_create_linux_tolerates_gio_failure(tmp_path, monkeypatch):
    """`gio` isn't installed on every distro — the shortcut must still
    be created when gio raises."""
    monkeypatch.setattr(Path, "home", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", False, create=True), \
         patch("subprocess.run",
               side_effect=FileNotFoundError("gio: command not found")):
        target = _create_linux()
    assert target.exists()


# ─────────────────────────────────────────────────────────────────────────
# _create_windows
# ─────────────────────────────────────────────────────────────────────────

def test_create_windows_invokes_powershell(tmp_path, monkeypatch):
    """A successful run calls PowerShell with the WScript.Shell COM
    recipe and the created .lnk exists at the end."""
    monkeypatch.setattr(shortcut, "_windows_desktop", lambda: tmp_path)

    def fake_run(cmd, **kw):
        # Simulate the .lnk being created by the real PowerShell call.
        (tmp_path / "DJ Tracks.lnk").write_bytes(b"\x00")
        return MagicMock(stdout="", stderr="", returncode=0)

    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", False, create=True), \
         patch("subprocess.run", side_effect=fake_run) as run:
        target = shortcut._create_windows()

    assert target == tmp_path / "DJ Tracks.lnk"
    # First positional arg is the command list.
    assert run.call_args[0][0][0] == "powershell"
    # The script passed to -Command must include CreateShortcut.
    joined = " ".join(run.call_args[0][0])
    assert "CreateShortcut" in joined


def test_create_windows_raises_when_lnk_not_created(tmp_path, monkeypatch):
    """PowerShell ran but produced nothing (COM blocked, path denied) →
    we must surface a RuntimeError with a human message, not succeed
    silently."""
    monkeypatch.setattr(shortcut, "_windows_desktop", lambda: tmp_path)
    with patch("utils.shortcut._project_root", return_value=tmp_path), \
         patch.object(sys, "frozen", False, create=True), \
         patch("subprocess.run",
               return_value=MagicMock(stdout="", stderr="Access denied")):
        with pytest.raises(RuntimeError, match="Access denied"):
            shortcut._create_windows()


# ─────────────────────────────────────────────────────────────────────────
# create_shortcut — platform dispatcher
# ─────────────────────────────────────────────────────────────────────────

def test_create_shortcut_dispatches_to_windows():
    with patch.object(sys, "platform", "win32"), \
         patch("utils.shortcut._create_windows",
               return_value=Path("/x/DJ Tracks.lnk")) as fn:
        result = create_shortcut()
    fn.assert_called_once()
    assert result == Path("/x/DJ Tracks.lnk")


def test_create_shortcut_dispatches_to_macos():
    with patch.object(sys, "platform", "darwin"), \
         patch("utils.shortcut._create_macos",
               return_value=Path("/x/DJ Tracks.command")) as fn:
        create_shortcut()
    fn.assert_called_once()


def test_create_shortcut_dispatches_to_linux():
    """Anything that isn't win32 or darwin falls to the Linux path."""
    with patch.object(sys, "platform", "linux"), \
         patch("utils.shortcut._create_linux",
               return_value=Path("/x/DJ Tracks.desktop")) as fn:
        create_shortcut()
    fn.assert_called_once()
