"""
utils/dnd.py
=============
Optional drag-and-drop support via tkinterdnd2.

Degrades cleanly when the library or its native tcl extension is not
available — :func:`setup_text_drop` returns False and the caller can
simply not advertise the feature in the UI.
"""
from __future__ import annotations

from typing import Callable, Optional

try:
    from tkinterdnd2 import DND_TEXT                       # type: ignore[import]
    from tkinterdnd2.TkinterDnD import _require            # type: ignore[import]
    _AVAILABLE = True
except Exception:  # tcl extension not built / lib missing / platform unsupported
    _AVAILABLE = False
    DND_TEXT   = ""                                        # type: ignore[assignment]


def available() -> bool:
    """True if drag-and-drop can be wired up on this machine."""
    return _AVAILABLE


def setup_text_drop(root, widget, callback: Callable[[str], None]) -> bool:
    """
    Register *widget* as a drop target for plain text.  Calls
    ``callback(text)`` whenever the user drops something on it.

    Returns ``True`` if the binding was installed, ``False`` otherwise
    (e.g. tkinterdnd2 unavailable, or tcl extension load failure).
    """
    if not _AVAILABLE:
        return False
    try:
        _require(root)
        widget.drop_target_register(DND_TEXT)
        widget.dnd_bind("<<Drop>>", lambda ev: callback(getattr(ev, "data", "")))
        return True
    except Exception:
        return False
