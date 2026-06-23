"""
utils/atomic_io.py
===================
Crash-safe atomic file writes.

Writes go to a sibling ``.tmp`` file first, then ``os.replace`` swaps
it onto the real path in a single filesystem operation.  If the
process dies during the write, the original file stays intact.
"""
from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any


def atomic_write_text(path: Path, text: str, encoding: str = "utf-8") -> None:
    """
    Atomically write *text* to *path*.

    Args:
        path:     Destination path.
        text:     Content to write.
        encoding: Text encoding (default ``utf-8``).

    Raises:
        OSError: on any I/O failure; the temporary file is removed.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    try:
        with open(tmp, "w", encoding=encoding, newline="") as fh:
            fh.write(text)
            fh.flush()
            try:
                os.fsync(fh.fileno())
            except OSError:
                pass        # fsync isn't supported on every fs (e.g. some FUSE mounts)
        os.replace(tmp, path)
    except Exception:
        # Clean up the stray .tmp on failure.
        with contextlib.suppress(FileNotFoundError):
            tmp.unlink()
        raise


def atomic_write_json(path: Path, data: Any, *, indent: int = 2,
                       ensure_ascii: bool = False) -> None:
    """Convenience wrapper: serialise *data* as JSON and write atomically."""
    atomic_write_text(
        path,
        json.dumps(data, indent=indent, ensure_ascii=ensure_ascii),
    )
