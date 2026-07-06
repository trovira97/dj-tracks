"""
scripts/fix_voice_hub.py
========================
Cleanup: the initial `create_voice_hub.py` run created a duplicate
category (`🎧 VOZ`) because the server already had `🎙️ VOZ`.

This script:
1. Deletes the redundant `☕ Chill Lounge` and `🎵 Listening Party`
   (redundant with the existing Music Chill / DJ Booth).
2. Moves the `🎧 ➕ Crear canal de voz` trigger into the existing
   `🎙️ VOZ` category.
3. Deletes the now-empty `🎧 VOZ` category.

Idempotent — safe to re-run.
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
log = logging.getLogger("fix_voice_hub")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])


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

        # Find the existing (original) voice category by microphone emoji.
        original = discord.utils.find(
            lambda c: "🎙️" in c.name or "🎙" in c.name,
            guild.categories)
        if original is None:
            log.warning("Original 🎙️ VOZ category not found — aborting move")
            return
        log.info(f"Original voice category: {original.name}")

        # Delete redundant channels.
        for name in ("☕ Chill Lounge", "🎵 Listening Party"):
            ch = discord.utils.find(
                lambda c, n=name: c.name == n, guild.voice_channels)
            if ch:
                await ch.delete(reason="Redundant with existing voice channels")
                log.info(f"Deleted {name}")

        # Move trigger to original category.
        trigger = discord.utils.find(
            lambda c: "Crear canal de voz" in c.name, guild.voice_channels)
        if trigger:
            if trigger.category_id != original.id:
                await trigger.edit(category=original,
                                   reason="Consolidate voice category")
                log.info(f"Moved '{trigger.name}' → {original.name}")

        # Delete the empty 🎧 VOZ category if it exists and is empty.
        duplicate = discord.utils.find(
            lambda c: c.name == "🎧 VOZ", guild.categories)
        if duplicate:
            if not duplicate.channels:
                await duplicate.delete(reason="Empty duplicate category")
                log.info("Deleted empty 🎧 VOZ category")
            else:
                log.warning(f"🎧 VOZ still has {len(duplicate.channels)} "
                            "channels — not deleting")


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
