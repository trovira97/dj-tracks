"""Tests for ``utils/notifications.py`` — cross-platform toast notifications.

Fire-and-forget OS notifications shown when a download completes
(hooked from ui/gui.py:3936).  Tests cover the three platform
back-ends with subprocess mocked, plus the XML/AppleScript escape
logic that would otherwise let a track title with angle brackets
or quotes crash the toast.

Focus:
- ``_escape_xml`` — &, <, >, " all handled (& first to avoid double-escape)
- ``_send_windows`` — PowerShell invocation, title+body XML-escaped
  into the WinRT ToastGeneric template
- ``_send_macos`` — osascript ``display notification`` call, double-
  quotes escaped
- ``_send_linux`` — notify-send with app-name + 4s timeout; silent
  no-op when notify-send missing
- ``notify()`` — platform dispatcher, daemon thread, swallows every
  exception
"""
from __future__ import annotations

import sys
import threading
import time
from unittest.mock import patch

from utils import notifications
from utils.notifications import (
    _escape_xml,
    _send_linux,
    _send_macos,
    _send_windows,
    notify,
)


# ─────────────────────────────────────────────────────────────────────────
# _escape_xml
# ─────────────────────────────────────────────────────────────────────────

def test_escape_xml_ampersand_first():
    """& must escape FIRST — otherwise '&amp;' from a later escape would
    get its own & re-escaped into '&amp;amp;'."""
    assert _escape_xml("A & B") == "A &amp; B"


def test_escape_xml_handles_angle_brackets():
    assert _escape_xml("<script>") == "&lt;script&gt;"


def test_escape_xml_handles_double_quote():
    assert _escape_xml('say "hi"') == "say &quot;hi&quot;"


def test_escape_xml_plain_text_unchanged():
    assert _escape_xml("Daft Punk - Get Lucky") == "Daft Punk - Get Lucky"


def test_escape_xml_combined():
    """A real-ish track title with every special char."""
    assert (_escape_xml('A&B <feat. "C">')
            == "A&amp;B &lt;feat. &quot;C&quot;&gt;")


# ─────────────────────────────────────────────────────────────────────────
# _send_windows — PowerShell + WinRT toast
# ─────────────────────────────────────────────────────────────────────────

def test_send_windows_invokes_powershell():
    with patch("utils.notifications.subprocess.run") as run:
        _send_windows("Hello", "World")
    args = run.call_args[0][0]
    assert args[0] == "powershell"
    assert "-NoProfile" in args
    assert "-WindowStyle" in args
    assert "Hidden" in args


def test_send_windows_embeds_escaped_title_and_body():
    """Specials in title/body must land XML-escaped inside the toast."""
    with patch("utils.notifications.subprocess.run") as run:
        _send_windows("A & B", '"quoted"')
    cmd = run.call_args[0][0][-1]       # the -Command argument string
    assert "A &amp; B" in cmd
    assert "&quot;quoted&quot;" in cmd


def test_send_windows_uses_toast_generic_template():
    """Changing template name silently breaks the toast layout."""
    with patch("utils.notifications.subprocess.run") as run:
        _send_windows("x", "y")
    assert "ToastGeneric" in run.call_args[0][0][-1]
    assert "ToastNotificationManager" in run.call_args[0][0][-1]


def test_send_windows_timeout_passed():
    """We bound the PowerShell call so a stuck WinRT subsystem can't
    block the daemon thread forever."""
    with patch("utils.notifications.subprocess.run") as run:
        _send_windows("x", "y")
    assert run.call_args.kwargs.get("timeout") == 6


# ─────────────────────────────────────────────────────────────────────────
# _send_macos — osascript display notification
# ─────────────────────────────────────────────────────────────────────────

def test_send_macos_invokes_osascript():
    with patch("utils.notifications.subprocess.run") as run:
        _send_macos("Title", "Body")
    cmd = run.call_args[0][0]
    assert cmd[0] == "osascript"
    assert "-e" in cmd
    script = cmd[cmd.index("-e") + 1]
    assert 'display notification "Body"' in script
    assert 'with title "Title"' in script


def test_send_macos_escapes_double_quotes():
    """Unescaped `"` would break out of the AppleScript string literal."""
    with patch("utils.notifications.subprocess.run") as run:
        _send_macos('Title "x"', 'Body "y"')
    script = run.call_args[0][0][2]
    assert r'\"x\"' in script
    assert r'\"y\"' in script


# ─────────────────────────────────────────────────────────────────────────
# _send_linux — notify-send
# ─────────────────────────────────────────────────────────────────────────

def test_send_linux_invokes_notify_send_when_present():
    with patch("utils.notifications.shutil.which",
               return_value="/usr/bin/notify-send"), \
         patch("utils.notifications.subprocess.run") as run:
        _send_linux("Title", "Body")
    args = run.call_args[0][0]
    assert args[0] == "notify-send"
    assert "-a" in args
    assert "DJ Tracks" in args           # app name
    assert "-t" in args
    assert "4000" in args                # 4-second timeout
    assert "Title" in args
    assert "Body" in args


def test_send_linux_silent_noop_when_notify_send_missing():
    """Headless servers / minimal containers don't ship libnotify.
    We must not even attempt subprocess.run — crash-free silence."""
    with patch("utils.notifications.shutil.which", return_value=None), \
         patch("utils.notifications.subprocess.run") as run:
        _send_linux("Title", "Body")
    run.assert_not_called()


def test_send_linux_has_subprocess_timeout():
    with patch("utils.notifications.shutil.which",
               return_value="/usr/bin/notify-send"), \
         patch("utils.notifications.subprocess.run") as run:
        _send_linux("x", "y")
    assert run.call_args.kwargs.get("timeout") == 5


# ─────────────────────────────────────────────────────────────────────────
# notify() — platform dispatch + thread safety
# ─────────────────────────────────────────────────────────────────────────

def _wait_for_daemon_threads(timeout=2.0):
    """Join any non-main thread spawned since the test started."""
    for t in threading.enumerate():
        if t is not threading.main_thread() and t.is_alive():
            t.join(timeout=timeout)


def _run_notify_and_wait(platform_value, title="Title", body="Body"):
    """Run notify() with a mocked platform and wait for the daemon
    thread to finish so assertions see the subprocess call."""
    with patch.object(sys, "platform", platform_value), \
         patch("utils.notifications._send_windows") as w, \
         patch("utils.notifications._send_macos") as m, \
         patch("utils.notifications._send_linux") as l:
        notify(title, body)
        _wait_for_daemon_threads()
    return w, m, l


def test_notify_dispatches_windows_on_win32():
    w, m, l = _run_notify_and_wait("win32")
    w.assert_called_once_with("Title", "Body")
    m.assert_not_called()
    l.assert_not_called()


def test_notify_dispatches_macos_on_darwin():
    w, m, l = _run_notify_and_wait("darwin")
    m.assert_called_once_with("Title", "Body")
    w.assert_not_called()
    l.assert_not_called()


def test_notify_dispatches_linux_on_other():
    """Anything that isn't win32 or darwin → Linux path."""
    w, m, l = _run_notify_and_wait("linux")
    l.assert_called_once_with("Title", "Body")


def test_notify_returns_immediately():
    """``notify`` is fire-and-forget — must return before the subprocess
    completes.  We prove it by making the back-end sleep and checking
    the main thread continues."""
    started = time.monotonic()
    with patch.object(sys, "platform", "win32"), \
         patch("utils.notifications._send_windows",
               side_effect=lambda t, b: time.sleep(2)):
        notify("x", "y")
    elapsed = time.monotonic() - started
    # Should return in < 1 s even though the back-end sleeps 2s.
    assert elapsed < 1.0
    _wait_for_daemon_threads(timeout=3)


def test_notify_body_defaults_to_empty_string():
    """Call shape with only title must work."""
    with patch.object(sys, "platform", "win32"), \
         patch("utils.notifications._send_windows") as w:
        notify("Download done")
        _wait_for_daemon_threads()
    assert w.called
    assert w.call_args[0][0] == "Download done"
    assert w.call_args[0][1] == ""


def test_notify_swallows_backend_exception():
    """Backend raising must NOT propagate — a stuck PowerShell can't
    bubble up into the UI thread."""
    with patch.object(sys, "platform", "win32"), \
         patch("utils.notifications._send_windows",
               side_effect=RuntimeError("powershell crashed")):
        # Must not raise.
        notify("x", "y")
        _wait_for_daemon_threads()


def test_notify_uses_daemon_thread():
    """A non-daemon thread would prevent the app process from exiting
    cleanly if a notification is still in flight."""
    captured: list = []
    original = threading.Thread

    def _capture(*args, **kwargs):
        t = original(*args, **kwargs)
        captured.append(t)
        return t

    with patch.object(sys, "platform", "win32"), \
         patch("utils.notifications._send_windows"), \
         patch("utils.notifications.threading.Thread", side_effect=_capture):
        notify("x", "y")
        _wait_for_daemon_threads()

    assert len(captured) == 1
    assert captured[0].daemon is True
