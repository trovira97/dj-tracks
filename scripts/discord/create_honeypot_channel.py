"""
scripts/create_honeypot_channel.py
====================================
One-shot: create ``#🚨-no-postear-aquí`` — the honeypot channel that
catches raid bots and scam accounts.

Design:
- Visible to @everyone (they need to see + post so we can catch them)
- Name is intentionally menacing so legitimate humans skip it
- Pinned message says "DO NOT POST — reserved for anti-raid, posting = ban"
- Koya's Honeypot module bans anyone who posts

Placed at the TOP of the channel list so nobody misses the warning.
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
log = logging.getLogger("create_honeypot_channel")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

CHANNEL_NAME = "🚨-no-postear-aquí"

WARNING_MSG = (
    "# 🚨 NO POSTEES AQUÍ\n\n"
    "**Este canal es una trampa anti-raid.**\n\n"
    "Cualquier mensaje enviado en este canal resulta en un **ban automático "
    "e inmediato**, sin excepciones.\n\n"
    "Los usuarios legítimos **NO deben interactuar** con este canal — ni "
    "postear, ni reaccionar, ni entrar a hilos.\n\n"
    "Si has llegado aquí por error, simplemente **cierra el canal**. "
    "Todo bien 👍"
)


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

        # Everyone can view + post; Koya has manage perms to ban+delete.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel = True,
                send_messages = True,
                read_message_history = True,
                add_reactions = False,          # no engagement bait
                create_public_threads = False,
                create_private_threads = False,
            ),
        }
        for bot in ("Koya", "DJ Tracks Bot"):
            role = discord.utils.get(guild.roles, name=bot)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel = True,
                    send_messages = True,
                    manage_messages = True,
                    read_message_history = True,
                )

        # Try to place at the very top: position=0.
        channel = await guild.create_text_channel(
            name = CHANNEL_NAME,
            topic = "TRAMPA · Postear aquí = ban automático. NO INTERACTÚES.",
            overwrites = overwrites,
            position = 0,
            reason = "Anti-raid honeypot",
        )
        log.info(f"Created #{channel.name} (id={channel.id})")

        # Post + pin the warning so first thing users see is DO NOT POST.
        msg = await channel.send(WARNING_MSG)
        await msg.pin(reason="Honeypot warning must be pinned")
        log.info("Posted and pinned warning message")

        log.info("")
        log.info("Next step — Koya dashboard → Honeypot → enable + point to:")
        log.info(f"    Canal trampa       : #{CHANNEL_NAME} (id={channel.id})")
        log.info("    Acción             : Banear")
        log.info("    Notificar          : #🛡️-mod-log")


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
