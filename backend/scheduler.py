"""
backend/scheduler.py
======================
Background tasks that run alongside the Discord gateway:

- ``weekly_digest_loop``  — every Monday at 10:00 UTC posts a
  community-health embed to the moderator channel.
- ``health_monitor_loop`` — pings the backend's HTTP health endpoint
  every 5 min; DMs the owner after 3 consecutive failures.

Both are launched from ``DJTracksBot.on_ready``.  Idempotent — they
survive gateway reconnections because we cancel-and-relaunch on
disconnect, but the loops are also individually robust to transient
failures.
"""
from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta, timezone

import discord
import httpx

log = logging.getLogger("dj_tracks.scheduler")

ACCENT_COLOR       = 0x00C8FF
OWNER_DISCORD_ID   = int(os.environ.get("OWNER_DISCORD_ID", "713713574161416232") or "0")
DIGEST_CHANNEL_ID  = int(os.environ.get("DIGEST_CHANNEL_ID", "0") or "0")
HEALTH_URL         = os.environ.get("SELF_HEALTH_URL",
                                     "https://dj-tracks-trovira97.fly.dev/")
HEALTH_INTERVAL_S  = 300      # 5 min
HEALTH_FAIL_LIMIT  = 3        # 3 misses = ~15 min down before we alert


# ────────────────────────────────────────────────────────────────────────────
# Weekly digest
# ────────────────────────────────────────────────────────────────────────────

def _next_monday_10utc(now: datetime | None = None) -> datetime:
    """Return the next Monday at 10:00 UTC strictly after *now*."""
    now = now or datetime.now(timezone.utc)
    # weekday(): Monday = 0, Sunday = 6
    days_ahead = (7 - now.weekday()) % 7
    target = (now + timedelta(days=days_ahead)).replace(
        hour=10, minute=0, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=7)
    return target


async def weekly_digest_loop(client: discord.Client, guild_id: int) -> None:
    """Sleep until next Monday 10:00 UTC, post digest, repeat."""
    log.info("[digest] loop started")
    while True:
        try:
            target = _next_monday_10utc()
            sleep_sec = (target - datetime.now(timezone.utc)).total_seconds()
            log.info(f"[digest] next run at {target.isoformat()} "
                     f"(in {sleep_sec/3600:.1f}h)")
            await asyncio.sleep(sleep_sec)
            await _post_digest(client, guild_id)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.error(f"[digest] loop error: {exc}")
            # Back off and keep looping; don't crash the task.
            await asyncio.sleep(3600)


async def _post_digest(client: discord.Client, guild_id: int) -> None:
    """Assemble + post the digest embed."""
    guild = client.get_guild(guild_id)
    if guild is None:
        log.warning("[digest] guild not cached, skipping")
        return

    # Resolve target channel: env var wins, else mod-chat by name.
    channel = None
    if DIGEST_CHANNEL_ID:
        channel = guild.get_channel(DIGEST_CHANNEL_ID)
    if channel is None:
        channel = discord.utils.find(
            lambda c: "mod-chat" in c.name and isinstance(c, discord.TextChannel),
            guild.channels,
        )
    if channel is None:
        log.warning("[digest] no target channel found")
        return

    # Query stats from SQLite.
    from app import db
    week_ago = int(time.time()) - 7 * 86400
    with db() as c:
        row = c.execute(
            "SELECT COUNT(*), COALESCE(SUM(amount), 0) FROM donors "
            "WHERE first_seen > ?", (week_ago,)).fetchone()
        new_donors, donated_eur = int(row[0] or 0), float(row[1] or 0)

        new_joins = c.execute(
            "SELECT COUNT(*) FROM member_events "
            "WHERE event='join' AND ts > ?", (week_ago,)).fetchone()[0]
        new_leaves = c.execute(
            "SELECT COUNT(*) FROM member_events "
            "WHERE event='leave' AND ts > ?", (week_ago,)).fetchone()[0]

        matched_q = c.execute(
            "SELECT COUNT(*) FROM faq_events "
            "WHERE matched_title IS NOT NULL AND ts > ?", (week_ago,)
        ).fetchone()[0]
        unmatched_rows = c.execute(
            "SELECT message, COUNT(*) AS cnt FROM faq_events "
            "WHERE matched_title IS NULL AND ts > ? "
            "GROUP BY message ORDER BY cnt DESC LIMIT 5", (week_ago,)
        ).fetchall()

    unmatched_total = sum(int(r[1]) for r in unmatched_rows)
    if not unmatched_rows:
        # There might be unmatched but not grouped; count anyway.
        with db() as c:
            unmatched_total = c.execute(
                "SELECT COUNT(*) FROM faq_events "
                "WHERE matched_title IS NULL AND ts > ?", (week_ago,)
            ).fetchone()[0]

    embed = discord.Embed(
        title="📊 Resumen semanal",
        description=f"Últimos 7 días · **{guild.name}**",
        color=ACCENT_COLOR,
        timestamp=datetime.now(timezone.utc),
    )
    embed.add_field(
        name="👥 Miembros",
        value=(f"Total: **{guild.member_count}**\n"
               f"Nuevos: **+{new_joins}**\n"
               f"Bajas: **-{new_leaves}**"),
        inline=True,
    )
    embed.add_field(
        name="💎 Donaciones",
        value=(f"Nuevos donantes: **{new_donors}**\n"
               f"Total: **{donated_eur:.2f}€**"),
        inline=True,
    )
    embed.add_field(
        name="🙋 FAQ · #ayuda",
        value=(f"Auto-respondidas: **{matched_q}**\n"
               f"Sin match: **{unmatched_total}**"),
        inline=True,
    )
    if unmatched_rows:
        top = "\n".join(
            f"• `{int(r[1])}x` — {r[0][:80]}"
            for r in unmatched_rows
        )
        embed.add_field(
            name="💡 Preguntas sin FAQ · considera añadirlas",
            value=top[:1024],
            inline=False,
        )
    embed.set_footer(text="DJ Tracks · digest automático")

    try:
        await channel.send(embed=embed)
        log.info(f"[digest] posted to #{channel.name}")
    except Exception as exc:
        log.error(f"[digest] send failed: {exc}")


# ────────────────────────────────────────────────────────────────────────────
# Backend health monitor
# ────────────────────────────────────────────────────────────────────────────

async def health_monitor_loop(client: discord.Client) -> None:
    """Ping HEALTH_URL every 5 min; DM owner after N consecutive misses.

    Catches the case where uvicorn is alive but its HTTP handler has
    hung — the bot process itself is fine (we're running in it), but
    the HTTP layer isn't responsive.  A truly dead process can't run
    this loop, so this is complementary to Fly's own healthchecks.
    """
    log.info(f"[health] monitoring {HEALTH_URL} every {HEALTH_INTERVAL_S}s")
    consecutive_fails = 0
    already_alerted = False
    async with httpx.AsyncClient(timeout=10) as http:
        while True:
            try:
                await asyncio.sleep(HEALTH_INTERVAL_S)
                try:
                    r = await http.get(HEALTH_URL)
                    ok = (r.status_code == 200)
                except Exception:
                    ok = False

                if ok:
                    if already_alerted:
                        # Send recovery notice.
                        await _dm_owner(
                            client,
                            f"✅ Backend recuperado tras "
                            f"{consecutive_fails * HEALTH_INTERVAL_S // 60} min "
                            f"caído."
                        )
                    consecutive_fails = 0
                    already_alerted = False
                else:
                    consecutive_fails += 1
                    if (consecutive_fails >= HEALTH_FAIL_LIMIT
                            and not already_alerted):
                        already_alerted = True
                        await _dm_owner(
                            client,
                            f"🚨 **Backend caído**\n\n"
                            f"El endpoint `{HEALTH_URL}` no responde "
                            f"desde hace "
                            f"~{consecutive_fails * HEALTH_INTERVAL_S // 60} min.\n\n"
                            f"Monitorización: https://fly.io/apps/"
                            f"dj-tracks-trovira97/monitoring"
                        )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.error(f"[health] loop error: {exc}")


async def _dm_owner(client: discord.Client, content: str) -> None:
    """DM the project owner.  Silent no-op if we can't reach them."""
    if not OWNER_DISCORD_ID:
        return
    try:
        owner = client.get_user(OWNER_DISCORD_ID)
        if owner is None:
            owner = await client.fetch_user(OWNER_DISCORD_ID)
        await owner.send(content)
        log.info(f"[dm] owner alerted")
    except discord.Forbidden:
        log.warning("[dm] owner has DMs closed — can't alert")
    except Exception as exc:
        log.warning(f"[dm] failed: {exc}")
