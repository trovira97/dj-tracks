"""Tests for the freemium gate — ``utils.donor_gate``.

The gate is the single most business-critical piece of the app: it
decides whether a user can start a download.  Bugs here either
give away paid access or lock out paying users.

The gate is server-authoritative but caches locally, and falls back
to an offline grace path when the server is unreachable.  These
tests cover all four quadrants (donor/non-donor × online/offline)
plus the state transitions triggered by ``record_download`` and
``set_donor``.
"""
from __future__ import annotations

import time
from unittest.mock import patch

import pytest

from utils import donor_gate
from utils.donor_gate import (
    FREE_LIMIT,
    can_download,
    get_state,
    record_download,
    set_donor,
)


# ── Fixture: fresh state per test ────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_state(tmp_path, monkeypatch):
    """Point ``_STATE`` at a throw-away usage.json AND reset its fields
    so tests don't leak into each other."""
    monkeypatch.setattr(donor_gate, "_usage_path",
                        lambda: tmp_path / "usage.json")
    # Rebuild the singleton against the temp path.
    donor_gate._STATE = donor_gate._State()
    yield


# ── Cache-hit paths (no server call) ─────────────────────────────────────

def test_donor_within_cache_ttl_always_allowed():
    """A cached donor never calls the server, always allowed."""
    donor_gate._STATE.is_donor    = True
    donor_gate._STATE.last_synced = time.time()  # fresh cache
    with patch.object(donor_gate, "_sync_with_server") as sync:
        assert can_download() is True
        sync.assert_not_called()


def test_non_donor_under_limit_within_cache_allowed():
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = FREE_LIMIT - 1
    donor_gate._STATE.last_synced    = time.time()
    with patch.object(donor_gate, "_sync_with_server") as sync:
        assert can_download() is True
        sync.assert_not_called()


def test_non_donor_at_limit_within_cache_blocked():
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = FREE_LIMIT
    donor_gate._STATE.last_synced    = time.time()
    with patch.object(donor_gate, "_sync_with_server") as sync:
        assert can_download() is False
        sync.assert_not_called()


# ── Server-authoritative paths (stale cache) ─────────────────────────────

def test_stale_cache_hits_server_and_honours_verdict():
    """When the cache is stale we call the server and use its allowed flag."""
    donor_gate._STATE.last_synced = 0  # stale
    server_resp = {
        "is_donor": False, "download_count": 3, "allowed": True,
    }
    with patch.object(donor_gate, "_sync_with_server",
                      return_value=server_resp) as sync:
        assert can_download() is True
        sync.assert_called_once_with("check")


def test_server_says_blocked_takes_precedence_over_stale_local():
    donor_gate._STATE.is_donor       = True   # local thinks we're a donor
    donor_gate._STATE.last_synced    = 0      # stale
    donor_gate._STATE.download_count = 0
    server_resp = {
        "is_donor": False, "download_count": FREE_LIMIT, "allowed": False,
    }
    with patch.object(donor_gate, "_sync_with_server", return_value=server_resp):
        assert can_download() is False
    # And the local state should now match what the server said.
    assert donor_gate._STATE.is_donor is False
    assert donor_gate._STATE.download_count == FREE_LIMIT


def test_server_promoting_to_donor_updates_local():
    """Ko-fi webhook already fired → server returns is_donor=True — the
    client should pick that up and cache it without needing app restart."""
    donor_gate._STATE.is_donor    = False
    donor_gate._STATE.last_synced = 0
    server_resp = {
        "is_donor": True, "download_count": FREE_LIMIT + 5, "allowed": True,
    }
    with patch.object(donor_gate, "_sync_with_server", return_value=server_resp):
        assert can_download() is True
    assert donor_gate._STATE.is_donor is True


# ── Offline-grace paths ──────────────────────────────────────────────────

def test_offline_donor_still_allowed():
    donor_gate._STATE.is_donor    = True
    donor_gate._STATE.last_synced = 0   # force server call
    with patch.object(donor_gate, "_sync_with_server", return_value=None):
        assert can_download() is True


def test_offline_non_donor_under_limit_allowed():
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = 3
    donor_gate._STATE.offline_count  = 5
    donor_gate._STATE.last_synced    = 0
    with patch.object(donor_gate, "_sync_with_server", return_value=None):
        assert can_download() is True   # max(3,5)=5 < FREE_LIMIT


def test_offline_non_donor_at_limit_blocked():
    """Even fully offline the free limit still applies — via offline_count."""
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = 0
    donor_gate._STATE.offline_count  = FREE_LIMIT
    donor_gate._STATE.last_synced    = 0
    with patch.object(donor_gate, "_sync_with_server", return_value=None):
        assert can_download() is False


# ── record_download semantics ───────────────────────────────────────────

def test_record_download_is_noop_for_donor():
    """Donors don't count — record_download does nothing local + no server call."""
    donor_gate._STATE.is_donor      = True
    donor_gate._STATE.offline_count = 0
    with patch.object(donor_gate, "_sync_with_server") as sync:
        record_download()
        sync.assert_not_called()
    assert donor_gate._STATE.offline_count == 0


def test_record_download_increments_offline_shadow():
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = 3
    donor_gate._STATE.offline_count  = 2
    with patch.object(donor_gate, "_sync_with_server", return_value=None):
        record_download()
    assert donor_gate._STATE.offline_count == 4   # max(3,2)+1


def test_record_download_syncs_with_server_authority():
    """Server's counter overwrites the offline shadow after a sync."""
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = 3
    donor_gate._STATE.offline_count  = 3
    server_resp = {
        "is_donor": False, "download_count": 4, "allowed": True,
    }
    with patch.object(donor_gate, "_sync_with_server", return_value=server_resp):
        record_download()
    assert donor_gate._STATE.download_count == 4
    assert donor_gate._STATE.offline_count == 4


# ── set_donor semantics ─────────────────────────────────────────────────

def test_set_donor_true_resets_counters():
    donor_gate._STATE.download_count = 8
    donor_gate._STATE.offline_count  = 8
    with patch.object(donor_gate, "_sync_with_server"):
        set_donor(True, discord_user_id="713713574161416232",
                        discord_username="trovira_97")
    assert donor_gate._STATE.is_donor is True
    assert donor_gate._STATE.download_count == 0
    assert donor_gate._STATE.offline_count == 0
    assert donor_gate._STATE.discord_user_id == "713713574161416232"


def test_set_donor_true_notifies_server():
    with patch.object(donor_gate, "_sync_with_server") as sync:
        set_donor(True, discord_user_id="123456789012345678")
    sync.assert_called_once_with("link")


def test_set_donor_false_does_not_touch_server():
    """Setting donor=False is a local revocation only — no server sync."""
    donor_gate._STATE.is_donor = True
    with patch.object(donor_gate, "_sync_with_server") as sync:
        set_donor(False)
    assert donor_gate._STATE.is_donor is False
    sync.assert_not_called()


# ── State persistence ───────────────────────────────────────────────────

def test_get_state_reports_remaining_free_for_non_donor():
    donor_gate._STATE.is_donor       = False
    donor_gate._STATE.download_count = 3
    s = get_state()
    assert s["remaining_free"] == FREE_LIMIT - 3
    assert s["is_donor"] is False


def test_get_state_reports_unlimited_for_donor():
    donor_gate._STATE.is_donor = True
    s = get_state()
    assert s["remaining_free"] == -1   # sentinel: unlimited


def test_get_state_uses_max_of_local_and_offline_count():
    """The visible counter is whichever is higher — server-known or
    offline shadow — so a user offline for a while doesn't see it
    'reset' when the server is unreachable."""
    donor_gate._STATE.download_count = 3
    donor_gate._STATE.offline_count  = 5
    assert get_state()["download_count"] == 5


def test_device_id_persists_across_state_reload(tmp_path, monkeypatch):
    """The device_id is generated once and stays stable across restarts —
    critical for the server to match a device to its counter."""
    monkeypatch.setattr(donor_gate, "_usage_path",
                        lambda: tmp_path / "usage.json")
    first  = donor_gate._State().device_id
    second = donor_gate._State().device_id
    assert first == second
    assert len(first) == 32   # uuid4().hex
