"""
utils/single_instance.py
=========================
Single-instance protection via a localhost socket bind.

Cleaner than a lock file: when the process dies, the OS releases the
port automatically — no stale lock to clean up.
"""
from __future__ import annotations

import socket
from typing import Optional


# Port chosen at random in the IANA dynamic range; unlikely to collide.
_PORT = 19_847
_HOST = "127.0.0.1"

_sock: Optional[socket.socket] = None


def acquire() -> bool:
    """
    Try to acquire the single-instance lock.

    Returns:
        ``True`` if this is the first instance and the lock was taken,
        ``False`` if another instance is already running.
    """
    global _sock
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 0)
        s.bind((_HOST, _PORT))
        s.listen(1)
        _sock = s
        return True
    except OSError:
        return False


def release() -> None:
    """Release the lock (called automatically at shutdown)."""
    global _sock
    if _sock is not None:
        try:
            _sock.close()
        except Exception:
            pass
        _sock = None
