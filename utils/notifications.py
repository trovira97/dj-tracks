"""
utils/notifications.py
=======================
Cross-platform native OS notifications.

- **Windows**: PowerShell + Windows.UI.Notifications (Toast XML).
- **macOS**:   ``osascript`` ``display notification``.
- **Linux**:   ``notify-send`` (libnotify).

All calls are non-blocking — actual delivery happens in a background
thread so the UI thread never waits on PowerShell / osascript spawning.
Failures are silent (best-effort delivery).
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import threading

_APP_NAME = "DJ Tracks"


def _escape_xml(text: str) -> str:
    return (text.replace("&", "&amp;")
                .replace("<", "&lt;")
                .replace(">", "&gt;")
                .replace('"', "&quot;"))


def _send_windows(title: str, body: str) -> None:
    t, b = _escape_xml(title), _escape_xml(body)
    ps = (
        "[Windows.UI.Notifications.ToastNotificationManager,"
        "Windows.UI.Notifications,ContentType=WindowsRuntime]|Out-Null;"
        "[Windows.Data.Xml.Dom.XmlDocument,"
        "Windows.Data.Xml.Dom.XmlDocument,ContentType=WindowsRuntime]|Out-Null;"
        "$xml=[Windows.Data.Xml.Dom.XmlDocument]::new();"
        f"$xml.LoadXml('<toast><visual><binding template=\"ToastGeneric\">"
        f"<text>{t}</text><text>{b}</text></binding></visual></toast>');"
        "$toast=[Windows.UI.Notifications.ToastNotification]::new($xml);"
        f"[Windows.UI.Notifications.ToastNotificationManager]::"
        f"CreateToastNotifier('{_APP_NAME}').Show($toast)"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps],
        capture_output=True, timeout=6,
    )


def _send_macos(title: str, body: str) -> None:
    # Escape double-quotes for the embedded AppleScript string.
    title = title.replace('"', r'\"')
    body  = body.replace('"', r'\"')
    subprocess.run(
        ["osascript", "-e",
         f'display notification "{body}" with title "{title}"'],
        capture_output=True, timeout=5,
    )


def _send_linux(title: str, body: str) -> None:
    if shutil.which("notify-send") is None:
        return
    subprocess.run(
        ["notify-send", "-a", _APP_NAME, "-t", "4000", title, body],
        capture_output=True, timeout=5,
    )


def notify(title: str, body: str = "") -> None:
    """
    Show a native OS notification.  Returns immediately; the real delivery
    happens in a daemon thread.  All errors are swallowed silently.

    Args:
        title: Heading text.
        body:  Body text (optional).
    """
    def _worker() -> None:
        try:
            if sys.platform == "win32":
                _send_windows(title, body)
            elif sys.platform == "darwin":
                _send_macos(title, body)
            else:
                _send_linux(title, body)
        except Exception:
            pass

    threading.Thread(target=_worker, daemon=True).start()
