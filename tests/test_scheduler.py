"""Tests for ``backend/scheduler.py`` — Discord bot background tasks.

Covers the two business-critical features without actually running
the asyncio loops or hitting Discord:
- Weekly digest (``_post_digest`` + ``_next_monday_10utc`` scheduling)
- Owner DM helper (``_dm_owner``) used by the health monitor

The ``app.db`` SQLite handle is mocked via a fake ``app`` module in
``sys.modules`` so no real database is created.  ``discord`` is the
real installed package (available in dev); the client, guild, channel
and user interactions use MagicMocks.

Focus:
- ``_next_monday_10utc``: correct Monday-after-now for every day of
  the week + edge cases around 10:00 Monday itself
- ``_post_digest``:
  * no-op when guild not cached
  * DIGEST_CHANNEL_ID env override wins
  * mod-chat auto-detect fallback by name
  * no-op when no target channel found
  * SQL counts flow into embed fields correctly
  * **unmatched_total counted via separate COUNT(*), not summed from
    the top-5 grouped rows** (regression guard for the fixed bug)
  * send exceptions logged but not propagated
- ``_dm_owner``:
  * no-op when OWNER_DISCORD_ID is 0
  * fetches user when get_user misses the cache
  * discord.Forbidden swallowed (DMs closed)
  * generic exceptions swallowed
"""
from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone
from types import ModuleType
from unittest.mock import AsyncMock, MagicMock, patch

import discord
import pytest


# ─────────────────────────────────────────────────────────────────────────
# Fixture — install a fake ``app`` module so ``from app import db`` works
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _fake_app_module():
    """``backend/scheduler.py:_post_digest`` does ``from app import db``.
    Install a stub so each test can inject its own db behaviour."""
    fake_app = ModuleType("app")
    fake_app.db = MagicMock()  # overwritten per test via patch
    sys.modules["app"] = fake_app
    yield fake_app
    sys.modules.pop("app", None)


# Import after the fake module hook so no eager failures.
from backend import scheduler  # noqa: E402


# ─────────────────────────────────────────────────────────────────────────
# _next_monday_10utc
# ─────────────────────────────────────────────────────────────────────────

def test_next_monday_from_tuesday():
    """Tuesday 12:00 UTC → next Monday 10:00 UTC (6 days later)."""
    now = datetime(2026, 10, 20, 12, 0, tzinfo=timezone.utc)  # Tuesday
    target = scheduler._next_monday_10utc(now)
    assert target.weekday() == 0        # Monday
    assert target.hour == 10
    assert target.minute == 0
    assert (target - now).days == 5     # Tue→Mon = 5 full days + 22h


def test_next_monday_from_sunday():
    """Sunday 23:00 UTC → Monday 10:00 UTC a few hours later."""
    now = datetime(2026, 10, 25, 23, 0, tzinfo=timezone.utc)  # Sunday
    target = scheduler._next_monday_10utc(now)
    assert target.weekday() == 0
    assert target.day == 26             # the very next day


def test_next_monday_from_monday_before_10am():
    """Monday 09:00 UTC → Monday 10:00 UTC same day."""
    now = datetime(2026, 10, 19, 9, 0, tzinfo=timezone.utc)  # Monday
    target = scheduler._next_monday_10utc(now)
    assert target.day == 19             # same day
    assert target.hour == 10


def test_next_monday_from_monday_at_exactly_10am():
    """Monday at 10:00 UTC: the just-ran digest just fired, so the next
    one must be the following week — not an instant re-run."""
    now = datetime(2026, 10, 19, 10, 0, tzinfo=timezone.utc)  # Monday 10:00
    target = scheduler._next_monday_10utc(now)
    assert target.day == 26
    assert target.weekday() == 0


def test_next_monday_from_monday_after_10am():
    """Monday 15:00 UTC → next Monday (7 days later)."""
    now = datetime(2026, 10, 19, 15, 0, tzinfo=timezone.utc)
    target = scheduler._next_monday_10utc(now)
    assert target.day == 26
    assert target.hour == 10


def test_next_monday_uses_utc_now_by_default():
    """Omitting the now arg defaults to datetime.now(UTC)."""
    target = scheduler._next_monday_10utc()
    assert target.tzinfo == timezone.utc
    assert target.weekday() == 0
    assert target.hour == 10


# ─────────────────────────────────────────────────────────────────────────
# _dm_owner — the health-monitor alert helper
# ─────────────────────────────────────────────────────────────────────────

def test_dm_owner_noop_when_owner_id_zero():
    """OWNER_DISCORD_ID=0 means no owner configured → silent no-op."""
    client = MagicMock()
    with patch.object(scheduler, "OWNER_DISCORD_ID", 0):
        asyncio.run(scheduler._dm_owner(client, "any message"))
    client.get_user.assert_not_called()


def test_dm_owner_sends_dm_when_user_cached():
    client = MagicMock()
    user = MagicMock()
    user.send = AsyncMock()
    client.get_user.return_value = user
    with patch.object(scheduler, "OWNER_DISCORD_ID", 12345):
        asyncio.run(scheduler._dm_owner(client, "backend down"))
    user.send.assert_awaited_once_with("backend down")


def test_dm_owner_fetches_user_when_cache_miss():
    """get_user returning None → fall back to fetch_user (async HTTP)."""
    client = MagicMock()
    client.get_user.return_value = None
    fetched = MagicMock()
    fetched.send = AsyncMock()
    client.fetch_user = AsyncMock(return_value=fetched)
    with patch.object(scheduler, "OWNER_DISCORD_ID", 12345):
        asyncio.run(scheduler._dm_owner(client, "msg"))
    client.fetch_user.assert_awaited_once_with(12345)
    fetched.send.assert_awaited_once()


def test_dm_owner_swallows_forbidden():
    """Owner has DMs closed → log warning, don't crash the loop."""
    client = MagicMock()
    user = MagicMock()
    user.send = AsyncMock(side_effect=discord.Forbidden(
        MagicMock(status=403, reason="Forbidden"), "DMs closed"))
    client.get_user.return_value = user
    with patch.object(scheduler, "OWNER_DISCORD_ID", 12345):
        # Must not raise.
        asyncio.run(scheduler._dm_owner(client, "msg"))


def test_dm_owner_swallows_generic_exception():
    """Any other exception (rate limit, network drop) is swallowed too."""
    client = MagicMock()
    client.get_user.side_effect = RuntimeError("gateway drop")
    with patch.object(scheduler, "OWNER_DISCORD_ID", 12345):
        asyncio.run(scheduler._dm_owner(client, "msg"))


# ─────────────────────────────────────────────────────────────────────────
# _post_digest helpers
# ─────────────────────────────────────────────────────────────────────────

def _mock_guild(name="DJ Tracks", member_count=42, channel=None):
    """Build a MagicMock Discord guild with one text channel the mod-chat
    name-match will find."""
    guild = MagicMock()
    guild.name = name
    guild.member_count = member_count
    chan = channel or MagicMock(spec=discord.TextChannel)
    chan.name = "🛡️-mod-chat"
    chan.send = AsyncMock()
    guild.channels = [chan]
    return guild, chan


def _db_context(rows):
    """Context-manager-returning MagicMock whose cursor's fetchone /
    fetchall yield the supplied ``rows`` list in order."""
    cursor = MagicMock()
    queue = list(rows)
    cursor.execute = MagicMock(return_value=cursor)
    cursor.fetchone = MagicMock(side_effect=lambda: queue.pop(0))
    cursor.fetchall = MagicMock(side_effect=lambda: queue.pop(0))
    ctx = MagicMock()
    ctx.__enter__ = MagicMock(return_value=cursor)
    ctx.__exit__ = MagicMock(return_value=False)
    return MagicMock(return_value=ctx)


# ─────────────────────────────────────────────────────────────────────────
# _post_digest
# ─────────────────────────────────────────────────────────────────────────

def test_post_digest_noop_when_guild_not_cached():
    """Guild not in the bot's cache → log + skip, no SQL query, no post."""
    client = MagicMock()
    client.get_guild.return_value = None
    asyncio.run(scheduler._post_digest(client, 999))


def test_post_digest_uses_env_channel_override_when_set():
    """If DIGEST_CHANNEL_ID env var is set, that channel wins over the
    name-based mod-chat auto-detect."""
    guild, _ = _mock_guild()
    override_chan = MagicMock(spec=discord.TextChannel)
    override_chan.name = "override"
    override_chan.send = AsyncMock()
    guild.get_channel.return_value = override_chan

    client = MagicMock()
    client.get_guild.return_value = guild

    sys.modules["app"].db = _db_context([
        (0, 0.0),   # donors row
        [0],        # new_joins fetchone
        [0],        # new_leaves
        [0],        # matched_q
        [0],        # unmatched_total
        [],         # unmatched_rows fetchall
    ])

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 777777):
        asyncio.run(scheduler._post_digest(client, 42))

    guild.get_channel.assert_called_once_with(777777)
    override_chan.send.assert_awaited_once()


def test_post_digest_auto_detects_mod_chat_channel():
    """No DIGEST_CHANNEL_ID → find any TextChannel whose name contains
    'mod-chat'."""
    guild, chan = _mock_guild()
    client = MagicMock()
    client.get_guild.return_value = guild

    sys.modules["app"].db = _db_context([
        (0, 0.0), [0], [0], [0], [0], [],
    ])

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 0):
        asyncio.run(scheduler._post_digest(client, 42))

    chan.send.assert_awaited_once()


def test_post_digest_noop_when_no_target_channel_found():
    """Neither env override nor mod-chat found → log + skip."""
    guild = MagicMock()
    guild.name = "DJ Tracks"
    guild.channels = []        # no channels at all
    guild.get_channel.return_value = None

    client = MagicMock()
    client.get_guild.return_value = guild

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 0):
        # Must not raise; the no-channel case returns early.
        asyncio.run(scheduler._post_digest(client, 42))


def test_post_digest_embed_carries_counts_from_db():
    """Full happy path: counts queried from DB land in the embed fields."""
    guild, chan = _mock_guild(member_count=100)
    client = MagicMock()
    client.get_guild.return_value = guild

    sys.modules["app"].db = _db_context([
        (3, 15.50),                   # 3 new donors / 15.50€
        [7],                          # new_joins
        [2],                          # new_leaves
        [12],                         # matched_q
        [8],                          # unmatched_total (SEPARATE query)
        [("why doesn't it work?", 3),
         ("spotify broke",         2),
         ("how to update?",        1)],  # unmatched_rows top-5
    ])

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 0):
        asyncio.run(scheduler._post_digest(client, 42))

    chan.send.assert_awaited_once()
    embed = chan.send.call_args.kwargs["embed"]
    assert "Resumen semanal" in embed.title

    # Fields: 0=Miembros, 1=Donaciones, 2=FAQ, 3=unmatched top-5
    members = embed.fields[0].value
    assert "Total: **100**" in members
    assert "+7" in members
    assert "-2" in members

    donations = embed.fields[1].value
    assert "**3**" in donations
    assert "15.50€" in donations

    faq = embed.fields[2].value
    assert "**12**" in faq
    # REGRESSION GUARD: unmatched headline = 8 (COUNT(*)), not sum(top-5)=6
    assert "**8**" in faq


def test_post_digest_unmatched_count_uses_total_not_grouped_sum():
    """REGRESSION guard for the undercount bug: when more distinct
    unmatched questions exist than the top-5 shows, the headline count
    MUST be the full tail, not sum(top-5)."""
    guild, chan = _mock_guild()
    client = MagicMock()
    client.get_guild.return_value = guild

    # 23 unmatched total but top-5 only shows the first 5.
    sys.modules["app"].db = _db_context([
        (0, 0.0), [0], [0], [0],
        [23],                             # unmatched_total: 23
        [("q1", 5), ("q2", 4), ("q3", 3),
         ("q4", 2), ("q5", 1)],           # sum = 15 (not 23)
    ])

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 0):
        asyncio.run(scheduler._post_digest(client, 42))

    embed = chan.send.call_args.kwargs["embed"]
    faq_field = embed.fields[2].value
    assert "**23**" in faq_field      # the real total
    assert "**15**" not in faq_field  # NOT the sum of the top-5


def test_post_digest_skips_top5_field_when_no_unmatched():
    """If there are zero unmatched questions, don't add the empty 'top'
    field — it would be an empty bullet list."""
    guild, chan = _mock_guild()
    client = MagicMock()
    client.get_guild.return_value = guild

    sys.modules["app"].db = _db_context([
        (0, 0.0), [0], [0], [10], [0], [],   # 10 matched, 0 unmatched
    ])

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 0):
        asyncio.run(scheduler._post_digest(client, 42))

    embed = chan.send.call_args.kwargs["embed"]
    field_names = [f.name for f in embed.fields]
    assert not any("sin FAQ" in n for n in field_names)


def test_post_digest_swallows_send_exception():
    """If channel.send raises (missing perms, rate limit), log + continue
    — the next week's run must not be blocked."""
    guild, chan = _mock_guild()
    chan.send = AsyncMock(side_effect=discord.HTTPException(
        MagicMock(status=500), "server error"))
    client = MagicMock()
    client.get_guild.return_value = guild

    sys.modules["app"].db = _db_context([
        (0, 0.0), [0], [0], [0], [0], [],
    ])

    with patch.object(scheduler, "DIGEST_CHANNEL_ID", 0):
        # Must not raise.
        asyncio.run(scheduler._post_digest(client, 42))
