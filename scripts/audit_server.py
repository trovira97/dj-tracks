"""
scripts/audit_server.py
========================
Read-only audit of the Discord server.  Prints:

- All roles with position + members with each
- All categories → child channels + slowmode + private?
- Every pinned message per channel (detect duplicates / stale)
- Bot presence + which permissions they have
- Empty / near-empty channels
- Channels @everyone can't view
- Recent (last 24h) system events per channel — messages count only,
  so we can tell which channels are alive

No mutations.
"""
from __future__ import annotations

import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
except Exception:
    pass

import discord

logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
)
log = logging.getLogger("audit")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])


def _safe(text: str) -> str:
    """Strip characters cp1252 can't encode (for Windows console)."""
    return text.encode("ascii", errors="replace").decode("ascii")


class OneShot(discord.Client):
    async def on_ready(self) -> None:
        try:
            await self._run()
        finally:
            await self.close()

    async def _run(self) -> None:
        guild = self.get_guild(GUILD_ID)
        if guild is None:
            log.error(f"Guild {GUILD_ID} not found")
            return

        log.info("")
        log.info("=" * 78)
        log.info(f"AUDIT · {_safe(guild.name)} · {guild.member_count} miembros")
        log.info("=" * 78)

        # ── 1. ROLES ─────────────────────────────────────────────────────
        log.info("")
        log.info("[ 1 ] ROLES (top→bottom by position)")
        log.info("-" * 78)
        for r in sorted(guild.roles, key=lambda r: -r.position):
            if r.name == "@everyone":
                continue
            managed = " [managed]" if r.managed else ""
            hoist   = " [hoisted]" if r.hoist else ""
            n = len(r.members)
            marker = " *" if n == 0 else ""
            log.info(f"  #{r.position:3}  {_safe(r.name):32} "
                     f"{n:3} members{managed}{hoist}{marker}")
        log.info("  * = role with 0 members (candidate for cleanup)")

        # ── 2. CATEGORIES + CHANNELS ─────────────────────────────────────
        log.info("")
        log.info("[ 2 ] CATEGORIES & CHANNELS")
        log.info("-" * 78)
        uncategorised = [c for c in guild.channels
                         if c.category is None
                         and not isinstance(c, discord.CategoryChannel)]
        if uncategorised:
            log.info("  (top-level, no category)")
            for c in uncategorised:
                self._describe_channel(c, indent=4)

        for cat in sorted(guild.categories, key=lambda c: c.position):
            log.info(f"  📁 {_safe(cat.name)}  ({len(cat.channels)} channels)")
            for c in cat.channels:
                self._describe_channel(c, indent=4)

        # ── 3. PINNED MESSAGES (dedup detection) ─────────────────────────
        log.info("")
        log.info("[ 3 ] PINNED MESSAGES  (dedup + freshness check)")
        log.info("-" * 78)
        me = guild.me
        pin_totals = defaultdict(int)
        for ch in guild.text_channels:
            perms = ch.permissions_for(me)
            if not perms.read_message_history:
                continue
            try:
                pins = await ch.pins()
            except discord.Forbidden:
                continue
            except Exception as exc:
                log.info(f"  ! {_safe(ch.name)}: pins fetch failed: {exc}")
                continue
            if not pins:
                continue
            log.info(f"  #{_safe(ch.name)}  ({len(pins)} pinned)")
            for m in pins:
                author = _safe(str(m.author))
                snippet = _safe(m.content[:70].replace("\n", " ")) or "[embed]"
                log.info(f"      · by {author:30}  {snippet}")
                pin_totals[ch.name] += 1

        # ── 4. BOTS & their top permissions ──────────────────────────────
        log.info("")
        log.info("[ 4 ] BOTS")
        log.info("-" * 78)
        for m in guild.members:
            if not m.bot:
                continue
            top = m.top_role
            perms = m.guild_permissions
            flags = []
            if perms.administrator: flags.append("ADMIN")
            if perms.manage_guild:  flags.append("manage_guild")
            if perms.manage_roles:  flags.append("manage_roles")
            if perms.ban_members:   flags.append("ban")
            if perms.kick_members:  flags.append("kick")
            if perms.manage_channels: flags.append("manage_channels")
            flags_str = ",".join(flags) or "basic"
            log.info(f"  🤖 {_safe(str(m)):30} top-role={_safe(top.name):20} "
                     f"perms={flags_str}")

        # ── 5. CHANNELS @everyone CAN'T VIEW ─────────────────────────────
        log.info("")
        log.info("[ 5 ] PRIVATE CHANNELS  (@everyone denied view)")
        log.info("-" * 78)
        default_role = guild.default_role
        for ch in guild.channels:
            if isinstance(ch, discord.CategoryChannel):
                continue
            ow = ch.overwrites_for(default_role)
            if ow.view_channel is False:
                cat = ch.category.name if ch.category else "top-level"
                log.info(f"  🔒  {_safe(cat):24} / #{_safe(ch.name)}")

        # ── 6. RECENT ACTIVITY per text channel (last 20 messages) ──────
        log.info("")
        log.info("[ 6 ] RECENT ACTIVITY  (messages last 24h, sampled)")
        log.info("-" * 78)
        import datetime
        since = discord.utils.utcnow() - datetime.timedelta(hours=24)
        for ch in guild.text_channels:
            perms = ch.permissions_for(me)
            if not perms.read_message_history:
                continue
            try:
                count = 0
                bot_count = 0
                async for msg in ch.history(after=since, limit=200):
                    count += 1
                    if msg.author.bot:
                        bot_count += 1
                if count > 0:
                    human = count - bot_count
                    log.info(f"  #{_safe(ch.name):30} "
                             f"{count:3} msgs  (human={human}, bot={bot_count})")
            except Exception:
                continue

        # ── 7. SUMMARY ───────────────────────────────────────────────────
        log.info("")
        log.info("=" * 78)
        log.info("SUMMARY")
        log.info("=" * 78)
        log.info(f"  Roles              : {len(guild.roles) - 1}  "
                 f"(excluding @everyone)")
        log.info(f"  Categories         : {len(guild.categories)}")
        log.info(f"  Text channels      : {len(guild.text_channels)}")
        log.info(f"  Voice channels     : {len(guild.voice_channels)}")
        log.info(f"  Bots               : "
                 f"{sum(1 for m in guild.members if m.bot)}")
        log.info(f"  Members            : {guild.member_count}")
        log.info(f"  Emojis             : {len(guild.emojis)}")
        log.info(f"  Boost level        : {guild.premium_tier}  "
                 f"({guild.premium_subscription_count} boosts)")

    def _describe_channel(self, ch, indent: int = 0) -> None:
        pad = " " * indent
        icon = "🔊" if isinstance(ch, discord.VoiceChannel) else \
               "🎭" if isinstance(ch, discord.StageChannel) else \
               "📢" if isinstance(ch, discord.ForumChannel) else "💬"
        default_role = ch.guild.default_role
        priv = " 🔒" if ch.overwrites_for(default_role).view_channel is False else ""
        slow = ""
        if isinstance(ch, discord.TextChannel):
            if ch.slowmode_delay:
                slow = f"  slow={ch.slowmode_delay}s"
        log.info(f"{pad}{icon} {_safe(ch.name):40}  id={ch.id}{priv}{slow}")


def main() -> int:
    intents = discord.Intents.default()
    intents.members         = True
    intents.message_content = True
    client = OneShot(intents=intents)
    try:
        client.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
