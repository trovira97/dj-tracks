"""
utils/donor_gate.py
====================
Freemium gate — server-authoritative.

The download counter and donor flag live on the backend, not on disk.
The local app keeps:
  - a device_id (random UUID, generated once on first run)
  - a short-lived cache of the server's last verdict
  - the discord_user_id once the user has linked their account

If the backend is unreachable, the client falls into an *offline
grace* window: it keeps counting locally and re-syncs as soon as the
server is back, so a network blip doesn't lock you out — but if you
go offline indefinitely the local counter still kicks in at 10.

NOTE: like every client-side check, this is honour-system at the
mechanical level (the .exe can be modified).  The point is that the
SERVER owns the counter — so removing the local check buys you
nothing if you ever talk to the backend again, and your donor status
can never be forged because Discord roles are decided server-side.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Optional

log = logging.getLogger("dj_tracks.donor")

FREE_LIMIT = 10                  # mirrors backend's FREE_LIMIT
CACHE_TTL_SEC = 60               # how long a positive check stays cached
OFFLINE_GRACE_SEC = 24 * 3600    # how long to trust local data if server is down


def _usage_path() -> Path:
    try:
        from utils.paths import config_dir
        return config_dir() / "usage.json"
    except Exception:
        return Path("config/usage.json")


class _State:
    """Single-process lock-protected view of usage.json (local cache only)."""

    _LOCK = threading.Lock()

    def __init__(self) -> None:
        self.device_id: str = ""
        self.discord_user_id: str = ""
        self.discord_username: str = ""
        # Last successful verdict received from the server.
        self.is_donor:       bool  = False
        self.download_count: int   = 0     # last-known SERVER count
        self.last_synced:    float = 0.0
        # Local-only counter for offline grace.
        self.offline_count:  int   = 0
        self._load()
        if not self.device_id:
            self.device_id = uuid.uuid4().hex
            self._save()

    def _load(self) -> None:
        p = _usage_path()
        if not p.exists():
            return
        try:
            # utf-8-sig tolerates an optional BOM written by some editors.
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            self.device_id        = str(data.get("device_id", ""))
            self.discord_user_id  = str(data.get("discord_user_id", ""))
            self.discord_username = str(data.get("discord_username", ""))
            self.is_donor         = bool(data.get("is_donor", False))
            self.download_count   = int(data.get("download_count", 0))
            self.last_synced      = float(data.get("last_synced", 0))
            self.offline_count    = int(data.get("offline_count", 0))
        except Exception as exc:
            log.warning(f"[Donor] could not load usage.json: {exc}")

    def _save(self) -> None:
        p   = _usage_path()
        tmp = p.with_suffix(p.suffix + ".tmp")
        try:
            p.parent.mkdir(parents=True, exist_ok=True)
            tmp.write_text(json.dumps({
                "device_id":        self.device_id,
                "discord_user_id":  self.discord_user_id,
                "discord_username": self.discord_username,
                "is_donor":         self.is_donor,
                "download_count":   self.download_count,
                "last_synced":      self.last_synced,
                "offline_count":    self.offline_count,
            }, indent=2), encoding="utf-8")
            os.replace(tmp, p)
        except Exception as exc:
            log.warning(f"[Donor] could not save usage.json: {exc}")


_STATE = _State()


def _sync_with_server(action: str) -> Optional[dict]:
    """Call /usage/{action} with our device_id and return the server's
    state dict, or None on failure."""
    from utils import donor_client
    return donor_client.usage_call(
        action, _STATE.device_id, discord_id=_STATE.discord_user_id or None
    )


# ── Public API (same surface as before) ─────────────────────────────────────

def get_state() -> dict:
    """Snapshot of the locally-cached state."""
    with _State._LOCK:
        count = max(_STATE.download_count, _STATE.offline_count)
        return {
            "device_id":        _STATE.device_id,
            "download_count":   count,
            "is_donor":         _STATE.is_donor,
            "discord_user_id":  _STATE.discord_user_id,
            "discord_username": _STATE.discord_username,
            "free_limit":       FREE_LIMIT,
            "remaining_free":   -1 if _STATE.is_donor else max(0, FREE_LIMIT - count),
        }


def can_download() -> bool:
    """True if the user is allowed to start a new download.

    Hits the server when the cache is stale.  Falls back to the
    locally-known counter if the server is unreachable AND we're
    within the offline grace window — outside the window we still
    allow (network outages shouldn't permanently lock the app), but
    the local count keeps rising so the limit eventually kicks in
    even fully offline.
    """
    with _State._LOCK:
        cached = (time.time() - _STATE.last_synced) < CACHE_TTL_SEC
        if cached:
            if _STATE.is_donor:
                return True
            return _STATE.download_count < FREE_LIMIT

    server = _sync_with_server("check")
    if server is not None:
        with _State._LOCK:
            _STATE.is_donor       = bool(server.get("is_donor", False))
            _STATE.download_count = int(server.get("download_count", 0))
            _STATE.last_synced    = time.time()
            # Donors / fresh server data — reset the offline shadow.
            if _STATE.is_donor or _STATE.download_count > _STATE.offline_count:
                _STATE.offline_count = _STATE.download_count
            _STATE._save()
            return bool(server.get("allowed", False))

    # ── Offline path ──────────────────────────────────────────────────────
    with _State._LOCK:
        if _STATE.is_donor:
            return True
        total = max(_STATE.download_count, _STATE.offline_count)
        return total < FREE_LIMIT


def record_download() -> None:
    """Bump the counter after a successful download — both on the
    server (authoritative) and locally (offline shadow)."""
    with _State._LOCK:
        if _STATE.is_donor:
            return
        _STATE.offline_count = max(_STATE.offline_count,
                                   _STATE.download_count) + 1
        _STATE._save()
    server = _sync_with_server("record")
    if server is not None:
        with _State._LOCK:
            _STATE.is_donor       = bool(server.get("is_donor", False))
            _STATE.download_count = int(server.get("download_count", 0))
            _STATE.offline_count  = _STATE.download_count
            _STATE.last_synced    = time.time()
            _STATE._save()


def set_donor(is_donor: bool, *,
              discord_user_id: str = "",
              discord_username: str = "") -> None:
    """Persist a new donor link locally and notify the server so future
    /usage/check calls return is_donor=True from any device the user
    has registered with this Discord ID."""
    with _State._LOCK:
        _STATE.is_donor = is_donor
        if discord_user_id:
            _STATE.discord_user_id = discord_user_id
        if discord_username:
            _STATE.discord_username = discord_username
        if is_donor:
            _STATE.download_count = 0
            _STATE.offline_count  = 0
        _STATE.last_synced = time.time()
        _STATE._save()
    if is_donor and _STATE.discord_user_id:
        _sync_with_server("link")


def reset_counter() -> None:
    """Local-only reset.  Server keeps its counter (anti-bypass).
    Useful only after a confirmed upgrade to donor."""
    with _State._LOCK:
        _STATE.download_count = 0
        _STATE.offline_count  = 0
        _STATE._save()
