"""
backend/bot.py
===============
Discord bot for DJ Tracks — DM-only commands.

Two commands, both inspired by DarkBot:
  !donate <amount>  → DMs back the user's own Discord ID + a pre-filled
                      Ko-fi URL.  The user pastes the ID into Ko-fi's
                      message field and the webhook auto-grants the
                      Donor role.
  !fixrole          → if the user already donated and is in our donors
                      table, re-assigns the Donor role (useful when
                      Discord forgets, the user leaves and re-joins,
                      or the role was manually removed).

The bot keeps a persistent WebSocket connection to Discord (gateway).
It's launched in FastAPI's startup hook so a single process serves
both HTTP and Discord at the same time.
"""
from __future__ import annotations

import logging
import os
import re

import discord

log = logging.getLogger("dj_tracks.bot")

DISCORD_BOT_TOKEN     = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID      = int(os.environ["DISCORD_GUILD_ID"])
DISCORD_DONOR_ROLE_ID = int(os.environ["DISCORD_DONOR_ROLE_ID"])
KOFI_USERNAME         = os.environ.get("KOFI_USERNAME", "trovira_97")

_DONATE_RE  = re.compile(r"^!donate\s+(\d+(?:[.,]\d+)?)\s*€?\s*$", re.I)
_FIXROLE_RE = re.compile(r"^!fixrole\s*$", re.I)
_HELP_RE    = re.compile(r"^!(help|comandos)\s*$", re.I)

ACCENT_COLOR = 0x00C8FF      # cyan, matches the app


class DJTracksBot(discord.Client):
    async def on_ready(self) -> None:
        log.info(f"[Bot] Logged in as {self.user} (id={self.user.id})")
        try:
            await self.change_presence(
                activity=discord.Game(name="!donate · !fixrole · !help"),
                status=discord.Status.online,
            )
        except Exception as exc:
            log.warning(f"[Bot] could not set presence: {exc}")

    async def on_message(self, message: discord.Message) -> None:
        # DM only — ignore everything in guilds.
        if message.guild is not None or message.author.bot:
            return

        content = message.content.strip()

        m = _DONATE_RE.match(content)
        if m:
            await self._handle_donate(message.author, m.group(1))
            return

        if _FIXROLE_RE.match(content):
            await self._handle_fixrole(message.author)
            return

        if _HELP_RE.match(content) or content.lower() == "hi" or content == "":
            await self._handle_help(message.author)
            return

    # ── Commands ───────────────────────────────────────────────────────────
    async def _handle_donate(self, user: discord.User, amount_raw: str) -> None:
        amount = amount_raw.replace(",", ".")
        kofi_url = f"https://ko-fi.com/{KOFI_USERNAME}/?donateamount={amount}"
        embed = discord.Embed(
            title=f"Donación de {amount}€ para DJ Tracks",
            color=ACCENT_COLOR,
            description=(
                "¡Gracias por considerar apoyar el proyecto! "
                "Cada donación desbloquea acceso completo, sin límite, "
                "para siempre."
            ),
        )
        embed.add_field(
            name="🔗  Donar en Ko-fi",
            value=f"[Pulsa aquí para abrir Ko-fi]({kofi_url})",
            inline=False,
        )
        embed.add_field(
            name="⚠️  IMPORTANTE — pega esto en el mensaje de la donación",
            value=(
                f"```\n{user.id}\n```\n"
                f"Es **tu Discord User ID**.  Copialo del bloque de arriba "
                f"y pégalo en el campo de mensaje de Ko-fi antes de pagar.\n\n"
                f"Si se te olvida, también puedes usar **Vincular Discord** "
                f"en la app y se desbloqueará por tu email."
            ),
            inline=False,
        )
        embed.set_footer(
            text="DJ Tracks · El rol llega en segundos tras confirmar el pago"
        )
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            log.info(f"[Bot] could not DM {user} — DMs closed")

    async def _handle_fixrole(self, user: discord.User) -> None:
        """If the user is in our donors table but lost the role
        (left + rejoined the server, admin removed it by mistake, etc.),
        re-assign it."""
        # Local import — avoids circular import at module-load time.
        from app import _is_donor_id, discord_add_donor_role

        try:
            if not _is_donor_id(str(user.id)):
                await user.send(
                    "No constas como donante en nuestra base de datos.\n"
                    "Si donaste hace poco, espera unos minutos y vuelve a "
                    "intentarlo.  Si donaste pero no pegaste tu Discord ID "
                    "en el mensaje, abre la app y pulsa **Vincular Discord** — "
                    "te detectaremos por email."
                )
                return
            ok = await discord_add_donor_role(str(user.id))
            if ok:
                await user.send(
                    f"✓ Rol Donor restaurado.  ¡Gracias por seguir apoyando "
                    f"DJ Tracks!"
                )
            else:
                await user.send(
                    "Constas como donante pero no pude asignarte el rol.  "
                    "Probablemente no estés en el server.  Únete y vuelve a "
                    "ejecutar `!fixrole`."
                )
        except discord.Forbidden:
            log.info(f"[Bot] could not DM {user} — DMs closed")
        except Exception as exc:
            log.error(f"[Bot] fixrole error for {user}: {exc}")

    async def _handle_help(self, user: discord.User) -> None:
        embed = discord.Embed(
            title="Comandos disponibles",
            color=ACCENT_COLOR,
            description="Estos son los comandos que entiendo (sólo por DM):",
        )
        embed.add_field(
            name="!donate <importe>",
            value=("Te devuelvo un enlace personalizado para donar en Ko-fi "
                   "con tu Discord ID listo para pegar.  Ej: `!donate 3`"),
            inline=False,
        )
        embed.add_field(
            name="!fixrole",
            value=("Si donaste pero perdiste el rol (saliste y volviste al "
                   "server, lo borró un admin por error…), te lo reasigno."),
            inline=False,
        )
        embed.add_field(
            name="!help",
            value="Te enseño esta lista.",
            inline=False,
        )
        try:
            await user.send(embed=embed)
        except discord.Forbidden:
            pass


# ── Bot instance + lifecycle ────────────────────────────────────────────────

_intents = discord.Intents.default()
_intents.message_content = True   # required to read DM content

bot = DJTracksBot(intents=_intents)


async def start_bot() -> None:
    """Start the Discord gateway connection.  Called from FastAPI's
    startup event.  Auto-reconnects on disconnect via discord.py's
    built-in retry logic."""
    try:
        await bot.start(DISCORD_BOT_TOKEN)
    except Exception as exc:
        log.error(f"[Bot] gateway connection died: {exc}")


async def stop_bot() -> None:
    """Clean shutdown on FastAPI termination."""
    if not bot.is_closed():
        await bot.close()
