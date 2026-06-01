"""
providers/base_provider.py
===========================
.. deprecated::
    This module is no longer used. The canonical provider interface lives in
    ``providers/__init__.py`` (:class:`providers.MusicProvider`).
    This file is kept only for backward compatibility and will be removed
    in a future release.
"""
# ruff: noqa
# mypy: ignore-errors
from providers import MusicProvider, TrackInfo  # re-export for any stale imports

__all__ = ["MusicProvider", "TrackInfo"]
