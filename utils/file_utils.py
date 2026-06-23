"""
utils/file_utils.py
====================
File-system helpers: path construction, collision avoidance, and formatting.
"""
from __future__ import annotations

import shutil
import uuid
from pathlib import Path
from typing import Union

from utils.validators import sanitize_filename

# Maximum number of collision-avoidance attempts before appending a UUID suffix.
_MAX_COLLISION_TRIES = 9_999


def build_output_path(
    base_folder: str,
    artist: str,
    album: str,
    title: str,
    ext: str,
    structure: str = "{artist}/{album}/{artist} - {title}",
) -> Path:
    """
    Construct a download destination path from a structure template.

    All name components are sanitised before interpolation to prevent
    path-traversal and illegal-character issues.

    Args:
        base_folder: Absolute (or relative) root download directory.
        artist:      Artist name.
        album:       Album name.
        title:       Track title.
        ext:         File extension without the leading dot.
        structure:   Path template; supports ``{artist}``, ``{album}``,
                     and ``{title}`` tokens.

    Returns:
        A :class:`~pathlib.Path` pointing to the intended output file.
        Parent directories are created automatically.
    """
    artist = sanitize_filename(artist or "Unknown Artist")
    album  = sanitize_filename(album  or "Unknown Album")
    title  = sanitize_filename(title  or "Unknown Title")

    relative = structure.format(artist=artist, album=album, title=title)
    path     = Path(base_folder) / f"{relative}.{ext}"
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def move_file(src: Path, dst: Path) -> Path:
    """
    Move *src* to *dst*, creating any missing parent directories.

    Returns:
        The destination :class:`~pathlib.Path`.
    """
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    return dst


def get_unique_path(path: Path) -> Path:
    """
    Return a path that does not collide with an existing file.

    Appends ``(1)``, ``(2)``, … up to :data:`_MAX_COLLISION_TRIES`.
    If all numeric slots are taken, appends a short UUID suffix instead.

    Args:
        path: Desired output path.

    Returns:
        A collision-free :class:`~pathlib.Path`.
    """
    if not path.exists():
        return path

    stem, suffix, parent = path.stem, path.suffix, path.parent

    for counter in range(1, _MAX_COLLISION_TRIES + 1):
        candidate = parent / f"{stem} ({counter}){suffix}"
        if not candidate.exists():
            return candidate

    # Last resort: append a UUID to guarantee uniqueness.
    short_uid = uuid.uuid4().hex[:8]
    return parent / f"{stem}_{short_uid}{suffix}"


def ensure_dir(path: Union[str, Path]) -> Path:
    """
    Create *path* as a directory (and all missing parents) if it does not exist.

    Returns:
        The resolved :class:`~pathlib.Path`.
    """
    p = Path(path)
    p.mkdir(parents=True, exist_ok=True)
    return p


def format_filesize(size_bytes: float) -> str:
    """
    Format *size_bytes* as a human-readable string with one decimal place.

    Examples::

        format_filesize(1024)        # "1.0 KB"
        format_filesize(1536)        # "1.5 KB"
        format_filesize(10_485_760)  # "10.0 MB"
    """
    size = float(size_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024:
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
