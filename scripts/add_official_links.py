"""
scripts/add_official_links.py
==============================
Boost GitHub / Ko-fi visibility across the server:

1. Set the guild description to include GitHub + Ko-fi + Web.
2. Post a pinned "🔗 Enlaces oficiales" embed in ``#👋-bienvenida``.

Idempotent — updates description in place, and if the pinned links
message already exists it edits it in place instead of posting a
duplicate.
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
log = logging.getLogger("add_official_links")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

GITHUB   = "https://github.com/trovira97/dj-tracks"
LATEST   = "https://github.com/trovira97/dj-tracks/releases/latest"
ISSUES   = "https://github.com/trovira97/dj-tracks/issues/new/choose"
KOFI     = "https://ko-fi.com/trovira_97"

ACCENT   = 0x00C8FF
MARKER   = "<!-- dj-tracks-official-links -->"  # for idempotency

SERVER_DESCRIPTION = (
    "Comunidad de DJ Tracks — el descargador de música open-source para DJs. "
    "Spotify · Apple Music · SoundCloud · YouTube · Beatport.\n\n"
    f"📦 GitHub: {GITHUB}\n"
    f"💎 Ko-fi:  {KOFI}"
)


def _build_embed() -> discord.Embed:
    e = discord.Embed(
        title="🔗 Enlaces oficiales",
        description=(
            "Todo lo que necesitas para empezar con DJ Tracks:"
        ),
        color=ACCENT,
    )
    e.add_field(
        name="📦 Descargar la app",
        value=f"[Última release]({LATEST})\nWindows, macOS y Linux.",
        inline=True,
    )
    e.add_field(
        name="💻 Código fuente",
        value=f"[GitHub — trovira97/dj-tracks]({GITHUB})\n"
              "Open-source · MIT",
        inline=True,
    )
    e.add_field(
        name="💎 Apoyar el proyecto",
        value=f"[Ko-fi — trovira_97]({KOFI})\n"
              "Desbloquea acceso ilimitado + rol Donor",
        inline=True,
    )
    e.add_field(
        name="🐛 Reportar bugs",
        value=f"[GitHub Issues]({ISSUES})\n"
              "Templates listos para rellenar",
        inline=True,
    )
    e.add_field(
        name="🙋 Ayuda rápida",
        value="Ve al canal `#🙋-ayuda`\n"
              "Bot responde FAQ al instante",
        inline=True,
    )
    e.add_field(
        name="📢 Novedades",
        value="Feed automático en `#🆕-changelog`\n"
              "Cada release aparece ahí",
        inline=True,
    )
    e.set_footer(text=f"DJ Tracks · {MARKER}")
    return e


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

        # ── 1. Server description ────────────────────────────────
        if "COMMUNITY" in guild.features:
            try:
                if guild.description != SERVER_DESCRIPTION:
                    await guild.edit(
                        description=SERVER_DESCRIPTION,
                        reason="Add GitHub + Ko-fi to server description",
                    )
                    log.info("Updated server description")
                else:
                    log.info("Server description already correct")
            except discord.Forbidden:
                log.warning("Can't edit guild description — need manage_guild")
            except Exception as exc:
                log.warning(f"Guild edit failed: {exc}")
        else:
            log.info("Guild is not a Community server — skipping description")

        # ── 2. Pinned links embed in #👋-bienvenida ──────────────
        welcome = discord.utils.find(
            lambda c: "bienvenida" in c.name.lower()
                      and isinstance(c, discord.TextChannel),
            guild.channels,
        )
        if welcome is None:
            log.warning("No #bienvenida channel found — skipping pinned links")
            return

        # Idempotency: look for an existing pinned message with our marker.
        embed = _build_embed()
        existing = None
        async for pin in welcome.pins():
            if pin.author != guild.me:
                continue
            if pin.embeds and MARKER in (pin.embeds[0].footer.text or ""):
                existing = pin
                break

        if existing:
            try:
                await existing.edit(embed=embed)
                log.info(f"Updated existing pinned links in #{welcome.name}")
            except Exception as exc:
                log.warning(f"Edit failed: {exc}")
        else:
            try:
                msg = await welcome.send(embed=embed)
                await msg.pin(reason="Official links reference")
                log.info(f"Posted + pinned new links embed in #{welcome.name}")
            except Exception as exc:
                log.warning(f"Post failed: {exc}")


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
