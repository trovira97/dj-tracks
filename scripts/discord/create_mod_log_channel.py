"""
scripts/create_mod_log_channel.py
==================================
One-shot: create ``#🛡️-mod-log`` for automated moderation alerts
(AutoMod, audit logs, ban events, etc.).

Placed inside the moderation category if one exists.  Only Moderador
and Owner can view — @everyone denied.

Usage:
    py scripts/create_mod_log_channel.py
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

try:
    from dotenv import load_dotenv
    load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
except Exception:
    pass

import discord

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("create_mod_log_channel")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

CHANNEL_NAME    = "🛡️-mod-log"
CATEGORY_HINTS  = ("MOD", "STAFF", "moderación")
FALLBACK_HINTS  = ("DJ TRACKS", "COMUNIDAD")


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

        existing = discord.utils.find(
            lambda c: c.name == CHANNEL_NAME, guild.text_channels)
        if existing:
            log.info(f"#{CHANNEL_NAME} already exists (id={existing.id})")
            return

        # Prefer a moderation-only category; fall back to a general one.
        category = None
        for hints in (CATEGORY_HINTS, FALLBACK_HINTS):
            for h in hints:
                category = discord.utils.find(
                    lambda c, h=h: h.lower() in c.name.lower(),
                    guild.categories)
                if category:
                    break
            if category:
                break

        if category:
            log.info(f"Placing under category: {category.name}")

        # Permissions: only mods + owner can view; @everyone locked out.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        for role_name in ("Moderador", "Owner", "Koya", "DJ Tracks Bot"):
            role = discord.utils.get(guild.roles, name=role_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    read_message_history=True,
                    send_messages=True,
                    embed_links=True,
                )

        channel = await guild.create_text_channel(
            name=CHANNEL_NAME,
            category=category,
            topic="Alertas automáticas: AutoMod, joins/leaves, cambios de rol. Solo lectura.",
            overwrites=overwrites,
            reason="Moderation log channel",
        )
        log.info(f"Created #{channel.name} (id={channel.id})")


def main() -> int:
    intents = discord.Intents.default()
    intents.members = True
    client = OneShot(intents=intents)
    try:
        client.run(TOKEN, log_handler=None)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
