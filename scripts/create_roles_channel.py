"""
scripts/create_roles_channel.py
================================
One-shot: create ``#🎨-roles`` in the "🎧 DJ TRACKS" category so users
can pick reaction roles managed by Koya.

Permissions:
- ``@everyone``: view + read history + add reactions.  **Cannot send.**
- Bots (Koya, DJ Tracks Bot): view + send + embed + manage messages,
  so Koya can post the reaction-role panel and pin it.

Idempotent — re-runnable, exits cleanly if the channel already exists.

Usage:
    py scripts/create_roles_channel.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from pathlib import Path

# Load env from backend/.env
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
log = logging.getLogger("create_roles_channel")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

CHANNEL_NAME = "🎨-roles"
CATEGORY_HINTS = ("DJ TRACKS", "COMUNIDAD", "GENERAL")

PINNED_MESSAGE = (
    "**🎨 ELIGE TUS INTERESES**\n\n"
    "Reacciona con los emojis de abajo para auto-asignarte roles.\n"
    "Puedes tener varios a la vez — no son excluyentes.\n\n"
    "🎧  **DJ Verified** — soy DJ activo (residente, freelance…)\n"
    "🎛️  **Beta Tester** — quiero probar builds pre-release\n"
    "🐛  **Bug Hunter** — reporto bugs y ayudo a QA\n"
    "📢  **Notif Releases** — ping cuando salga versión nueva\n"
    "🎉  **Notif Eventos** — ping para listening parties / streams\n\n"
    "_Para quitar un rol, retira tu reacción._"
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

        # Bail early if channel exists.
        existing = discord.utils.find(
            lambda c: c.name == CHANNEL_NAME,
            guild.text_channels,
        )
        if existing:
            log.info(f"Channel #{CHANNEL_NAME} already exists — nothing to do")
            log.info(f"Channel ID: {existing.id}")
            log.info(f"Use it: run  /reactionrole  inside it (or click and type)")
            return

        # Pick a category.
        category = None
        for hint in CATEGORY_HINTS:
            category = discord.utils.find(
                lambda c, h=hint: h.lower() in c.name.lower(),
                guild.categories,
            )
            if category:
                log.info(f"Placing channel under category: {category.name}")
                break
        if category is None:
            log.warning("No matching category found — channel will be top-level")

        # Build overwrites.
        overwrites = {
            guild.default_role: discord.PermissionOverwrite(
                view_channel=True,
                read_message_history=True,
                add_reactions=True,
                send_messages=False,
                send_messages_in_threads=False,
                create_public_threads=False,
                create_private_threads=False,
            ),
        }
        # Bot-friendly perms: whichever bot needs to post the panel.
        for bot_name in ("Koya", "DJ Tracks Bot"):
            role = discord.utils.get(guild.roles, name=bot_name)
            if role:
                overwrites[role] = discord.PermissionOverwrite(
                    view_channel=True,
                    send_messages=True,
                    embed_links=True,
                    attach_files=True,
                    manage_messages=True,
                    add_reactions=True,
                    read_message_history=True,
                )
                log.info(f"Granted post/manage rights to @{bot_name}")

        channel = await guild.create_text_channel(
            name=CHANNEL_NAME,
            category=category,
            topic="Auto-asignación de roles. Reacciona para desbloquear notificaciones.",
            overwrites=overwrites,
            reason="Reaction roles channel for Koya",
        )
        log.info(f"Created #{channel.name} (id={channel.id})")

        # Post + pin the intro message so the panel space is clear from day 1.
        try:
            msg = await channel.send(PINNED_MESSAGE)
            await msg.pin(reason="Instructions for the reaction role panel")
            log.info("Posted and pinned the intro message")
        except Exception as exc:
            log.warning(f"Couldn't post/pin intro message: {exc}")

        log.info("")
        log.info("Next step — in Discord, inside the new channel:")
        log.info("    /reactionrole create")
        log.info("Follow Koya's prompts using the emoji/role table from the docs.")


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
