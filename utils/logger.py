"""
utils/logger.py
================
Centralised logging configuration for DJ Tracks.

Creates a singleton :class:`logging.Logger` with:

- A rotating file handler (5 MB cap, 3 backups) stored in the logs/ directory.
- A console handler (WARNING level and above — keeps the terminal quiet).
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def get_logger(name: str = "dj_tracks") -> logging.Logger:
    """
    Return the shared application logger, creating it on first call.

    Args:
        name: Logger name (default ``"dj_tracks"``).

    Returns:
        A configured :class:`logging.Logger` instance.
    """
    logger = logging.getLogger(name)

    if logger.handlers:
        return logger   # Already configured — avoid duplicate handlers.

    logger.setLevel(logging.DEBUG)

    log_dir = Path(__file__).parent.parent / "logs"
    log_dir.mkdir(exist_ok=True)

    # ── Rotating file handler (DEBUG+) ────────────────────────────────────────
    _fmt = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        log_dir / "app.log",
        maxBytes    = 5 * 1024 * 1024,
        backupCount = 3,
        encoding    = "utf-8",
    )
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(_fmt)

    # ── Console handler (WARNING+ to keep terminal quiet) ─────────────────────
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.WARNING)
    console_handler.setFormatter(logging.Formatter("%(levelname)-8s | %(message)s"))

    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    return logger


#: Project-wide logger singleton.
log = get_logger("dj_tracks")
