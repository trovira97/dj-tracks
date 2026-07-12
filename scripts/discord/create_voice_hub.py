"""
scripts/create_voice_hub.py
============================
One-shot: create the "🎧 VOZ" category + a join-to-create voice channel
used by Koya's Voz Temporal module.

When a user joins ``🎧 ➕ Crear canal de voz``, Koya spawns a personal
temporary channel under the same category and moves the user there.
Empty temporary channels auto-delete.

Usage:
    py scripts/create_voice_hub.py
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
log = logging.getLogger("create_voice_hub")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

CATEGORY_NAME       = "🎧 VOZ"
TRIGGER_CHANNEL     = "🎧 ➕ Crear canal de voz"
CHILL_CHANNEL       = "☕ Chill Lounge"          # permanent, always available
LISTENING_CHANNEL   = "🎵 Listening Party"       # permanent, for group listen


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

        # ── Category ──────────────────────────────────────────────
        category = discord.utils.find(
            lambda c: c.name == CATEGORY_NAME, guild.categories)
        if category:
            log.info(f"Category {CATEGORY_NAME} already exists")
        else:
            category = await guild.create_category(
                name=CATEGORY_NAME,
                reason="Voice hub for Koya's temporary voice module")
            log.info(f"Created category {CATEGORY_NAME} (id={category.id})")

        # ── Trigger voice channel ─────────────────────────────────
        # Miembros only — @everyone can't join if not screened.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(view_channel=False),
        }
        miembro = discord.utils.get(guild.roles, name="Miembro")
        if miembro:
            overwrites[miembro] = discord.PermissionOverwrite(
                view_channel=True, connect=True, speak=True)

        trigger = discord.utils.find(
            lambda c: c.name == TRIGGER_CHANNEL, guild.voice_channels)
        if trigger is None:
            trigger = await guild.create_voice_channel(
                name=TRIGGER_CHANNEL,
                category=category,
                user_limit=1,          # join to spawn, kick to personal channel
                overwrites=overwrites,
                reason="Join-to-create trigger for Koya",
            )
            log.info(f"Created voice channel {TRIGGER_CHANNEL} "
                     f"(id={trigger.id})")
        else:
            log.info(f"Voice channel {TRIGGER_CHANNEL} already exists")

        # ── Permanent lounge (no auto-delete) ─────────────────────
        chill = discord.utils.find(
            lambda c: c.name == CHILL_CHANNEL, guild.voice_channels)
        if chill is None:
            chill = await guild.create_voice_channel(
                name=CHILL_CHANNEL,
                category=category,
                overwrites=overwrites,
                reason="Always-available voice lounge",
            )
            log.info(f"Created voice channel {CHILL_CHANNEL} (id={chill.id})")
        else:
            log.info(f"Voice channel {CHILL_CHANNEL} already exists")

        # ── Permanent listening party ─────────────────────────────
        listen = discord.utils.find(
            lambda c: c.name == LISTENING_CHANNEL, guild.voice_channels)
        if listen is None:
            listen = await guild.create_voice_channel(
                name=LISTENING_CHANNEL,
                category=category,
                overwrites=overwrites,
                reason="Group listening room",
            )
            log.info(f"Created voice channel {LISTENING_CHANNEL} "
                     f"(id={listen.id})")
        else:
            log.info(f"Voice channel {LISTENING_CHANNEL} already exists")

        log.info("")
        log.info("Next step — Koya dashboard → Voz Temporal:")
        log.info(f"  Canal activador   → {TRIGGER_CHANNEL}")
        log.info(f"  Categoría         → {CATEGORY_NAME}")
        log.info("  Plantilla nombre  → 🎧 Sala de {username}")
        log.info("  Límite usuarios   → 0 (ilimitado)")


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
