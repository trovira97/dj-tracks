"""
scripts/grant_koya_voice_view.py
=================================
Fix: the trigger voice channel excluded @everyone from viewing but
never gave Koya explicit view rights, so Koya's dashboard dropdown
can't list it.

This grants Koya view + move + manage rights on the trigger channel
(needed for the join-to-create flow — she has to see the channel,
detect user joins, and move them to the spawned personal room).
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
log = logging.getLogger("grant_koya_voice_view")


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

        koya = discord.utils.get(guild.roles, name="Koya")
        if koya is None:
            log.error("@Koya role not found")
            return

        trigger = discord.utils.find(
            lambda c: "Crear canal de voz" in c.name, guild.voice_channels)
        if trigger is None:
            log.error("Trigger voice channel not found")
            return

        await trigger.set_permissions(
            koya,
            view_channel     = True,
            connect          = True,
            move_members     = True,
            manage_channels  = True,
            reason           = "Koya needs to run the join-to-create flow",
        )
        log.info(f"Granted Koya view+manage on {trigger.name}")

        # Also give her rights on the parent category so spawned rooms
        # inherit them.
        if trigger.category is not None:
            await trigger.category.set_permissions(
                koya,
                view_channel     = True,
                connect          = True,
                move_members     = True,
                manage_channels  = True,
                reason           = "Koya manages spawned voice rooms in this category",
            )
            log.info(f"Granted Koya view+manage on category {trigger.category.name}")


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
