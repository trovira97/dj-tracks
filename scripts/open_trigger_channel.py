"""
scripts/open_trigger_channel.py
================================
Fix: Koya's dashboard filters voice channels by whether Koya can view
them AND lists only channels visible in a "normal" role list.  The
trigger's @everyone view=False override may be preventing it from
appearing.

Open @everyone view on the trigger — connecting is still gated by
the Miembro role.  Anyone can SEE the "click to spawn" channel; only
verified members can CONNECT and get a personal room.
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
log = logging.getLogger("open_trigger_channel")


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

        trigger = discord.utils.find(
            lambda c: "Crear canal de voz" in c.name, guild.voice_channels)
        if trigger is None:
            log.error("Trigger voice channel not found")
            return

        # Open view to everyone; keep connect gated by Miembro override.
        await trigger.set_permissions(
            guild.default_role,
            view_channel = True,
            connect      = False,      # only Miembro can connect
            reason       = "Make trigger visible so Koya can list it",
        )
        log.info(f"Opened @everyone view on {trigger.name}")

        # Ensure Miembro can still connect + speak.
        miembro = discord.utils.get(guild.roles, name="Miembro")
        if miembro:
            await trigger.set_permissions(
                miembro,
                view_channel = True,
                connect      = True,
                speak        = True,
                reason       = "Miembro can spawn personal rooms",
            )
            log.info(f"Confirmed @Miembro connect on {trigger.name}")


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
