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

import asyncio
import contextlib
import logging
import os
import re
import time

import discord

log = logging.getLogger("dj_tracks.bot")

DISCORD_BOT_TOKEN         = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID          = int(os.environ["DISCORD_GUILD_ID"])
DISCORD_DONOR_ROLE_ID     = int(os.environ["DISCORD_DONOR_ROLE_ID"])
KOFI_USERNAME             = os.environ.get("KOFI_USERNAME", "trovira_97")
# Optional public-announce channel for incoming donations.  Falsy = disabled.
KOFI_ANNOUNCE_CHANNEL_ID  = int(os.environ.get("KOFI_ANNOUNCE_CHANNEL_ID", "0") or "0")

# Discord snowflake IDs (17-20 digits) are stripped from public messages
# so we don't leak a donor's Discord ID pasted in the Ko-fi message field.
_SNOWFLAKE_STRIP_RE = re.compile(r"\b\d{17,20}\b")

_CURRENCY_SYMBOLS = {"EUR": "€", "USD": "$", "GBP": "£", "JPY": "¥"}

_DONATE_RE  = re.compile(r"^!donate\s+(\d+(?:[.,]\d+)?)\s*€?\s*$", re.I)
_FIXROLE_RE = re.compile(r"^!fixrole\s*$", re.I)
_HELP_RE    = re.compile(r"^!(help|comandos)\s*$", re.I)

ACCENT_COLOR = 0x00C8FF      # cyan, matches the app


class DJTracksBot(discord.Client):
    # Background tasks — launched once on first on_ready, cancelled on close.
    _bg_tasks: list[asyncio.Task] = []

    async def on_ready(self) -> None:
        log.info(f"[Bot] Logged in as {self.user} (id={self.user.id})")
        try:
            await self.change_presence(
                activity=discord.Game(name="!donate · !fixrole · !help"),
                status=discord.Status.online,
            )
        except Exception as exc:
            log.warning(f"[Bot] could not set presence: {exc}")

        # Launch background loops once — on_ready can fire again after a
        # reconnect, and we don't want duplicate schedulers.
        if not self._bg_tasks:
            import scheduler
            self._bg_tasks.append(asyncio.create_task(
                scheduler.weekly_digest_loop(self, DISCORD_GUILD_ID),
                name="weekly_digest",
            ))
            self._bg_tasks.append(asyncio.create_task(
                scheduler.health_monitor_loop(self),
                name="health_monitor",
            ))
            log.info("[Bot] background tasks started: digest + health")

    async def on_member_join(self, member: discord.Member) -> None:
        """Warm welcome for every new arrival.

        Two-pronged: a public embed in the welcome channel with @mention
        (so they feel greeted), plus a private DM with quick-start
        info they can bookmark.  DM gracefully skipped when the user
        has DMs from bots disabled.
        """
        if member.guild.id != DISCORD_GUILD_ID or member.bot:
            return

        # ── Log join for the weekly digest.
        with contextlib.suppress(Exception):
            from app import db
            with db() as c:
                c.execute(
                    "INSERT INTO member_events (user_id, username, event, ts) "
                    "VALUES (?, ?, 'join', ?)",
                    (str(member.id), str(member), int(time.time())),
                )

        # ── Public greeting in #welcome (Discord's designated system
        #    channel — user picks which one via Server Settings).
        try:
            welcome_channel = (
                member.guild.system_channel
                or discord.utils.find(
                    lambda c: "bienvenida" in c.name.lower()
                              and isinstance(c, discord.TextChannel),
                    member.guild.channels,
                )
            )
            if welcome_channel:
                public = discord.Embed(
                    title=f"¡Bienvenido, {member.display_name}! 🎧",
                    description=(
                        f"Un miembro más en la comunidad — ya somos "
                        f"**{member.guild.member_count}**. "
                        f"Preséntate en <#PLACEHOLDER_GENERAL> cuando quieras."
                    ),
                    color=ACCENT_COLOR,
                )
                public.set_thumbnail(url=member.display_avatar.url)
                # Fix the general channel mention on the fly.
                gen = discord.utils.find(
                    lambda c: c.name.endswith("-general"),
                    member.guild.text_channels)
                if gen:
                    public.description = public.description.replace(
                        "<#PLACEHOLDER_GENERAL>", gen.mention)
                await welcome_channel.send(
                    content=member.mention, embed=public)
        except discord.Forbidden:
            log.info("[Bot] no permission to greet in welcome channel")
        except Exception as exc:
            log.warning(f"[Bot] welcome greeting failed: {exc}")

        # ── Private DM with quick-start info.
        try:
            dm = discord.Embed(
                title="🎧  ¡Bienvenido a DJ Tracks!",
                color=ACCENT_COLOR,
                description=(
                    "Gracias por unirte a la comunidad.  Aquí tienes "
                    "todo lo que necesitas para empezar:"
                ),
            )
            dm.add_field(
                name="📦  Descargar la app",
                value="https://github.com/trovira97/dj-tracks/releases/latest",
                inline=False,
            )
            dm.add_field(
                name="🙋  Pedir ayuda",
                value="Escribe en el canal `#🙋-ayuda` — respondemos rápido.",
                inline=False,
            )
            dm.add_field(
                name="💎  Desbloquear acceso ilimitado",
                value=("Escríbeme `!donate <€>` por DM y te paso un enlace "
                       "Ko-fi personalizado."),
                inline=False,
            )
            dm.add_field(
                name="🐛  Reportar un bug",
                value="https://github.com/trovira97/dj-tracks/issues/new/choose",
                inline=False,
            )
            dm.set_footer(text="DJ Tracks · ¡Nos vemos en el server!")
            await member.send(embed=dm)
        except discord.Forbidden:
            log.info(f"[Bot] can't DM {member} — DMs closed")
        except Exception as exc:
            log.warning(f"[Bot] welcome DM failed: {exc}")

    async def on_member_remove(self, member: discord.Member) -> None:
        """Log leaves for the weekly digest."""
        if member.guild.id != DISCORD_GUILD_ID or member.bot:
            return
        with contextlib.suppress(Exception):
            from app import db
            with db() as c:
                c.execute(
                    "INSERT INTO member_events (user_id, username, event, ts) "
                    "VALUES (?, ?, 'leave', ?)",
                    (str(member.id), str(member), int(time.time())),
                )

    async def on_member_update(self,
                                before: discord.Member,
                                after:  discord.Member) -> None:
        """Detect when the Donor role is added or removed (manually by
        an admin, via the !donate flow, or any other way) and keep our
        donors table in sync in real time.

        This is the path the project owner uses when granting free
        access to friends: assign the role in Discord by hand, and the
        bot mirrors it into the DB so the next /usage/check from that
        friend's machine returns is_donor=true automatically.
        """
        if before.guild.id != DISCORD_GUILD_ID:
            return
        had = any(r.id == DISCORD_DONOR_ROLE_ID for r in before.roles)
        has = any(r.id == DISCORD_DONOR_ROLE_ID for r in after.roles)
        if had == has:
            return

        import time

        from app import db
        now = int(time.time())
        discord_id = str(after.id)

        if has:
            with db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO donors "
                    "(discord_id, username, email, amount, "
                    " first_seen, last_seen) VALUES (?, ?, "
                    " (SELECT email FROM donors WHERE discord_id = ?), "
                    " (SELECT amount FROM donors WHERE discord_id = ?), "
                    " COALESCE((SELECT first_seen FROM donors WHERE discord_id = ?), ?), "
                    " ?)",
                    (discord_id, after.name, discord_id, discord_id,
                     discord_id, now, now))
            log.info(f"[Bot] Donor role granted to {after} ({discord_id}) — "
                     f"added to donors")
            # Friendly DM so the user knows their access is live.
            with contextlib.suppress(discord.Forbidden):
                await after.send(
                    "🎉 ¡Felicidades! Has recibido el rol **Donor** en "
                    "DJ Tracks.  Tu app ya tiene acceso ilimitado a partir "
                    "del próximo arranque (o tras pulsar cualquier botón "
                    "que toque el backend, en segundos)."
                )
        else:
            with db() as c:
                c.execute("DELETE FROM donors WHERE discord_id = ?",
                          (discord_id,))
            log.info(f"[Bot] Donor role removed from {after} ({discord_id}) "
                     f"— removed from donors")

    async def on_message(self, message: discord.Message) -> None:
        # Silently delete Discord's "X pinned a message" system notices
        # so the channel history stays clean.  Nothing to gain from
        # keeping those — the pin itself is visible in the pin list.
        if (message.guild is not None
                and message.type == discord.MessageType.pins_add):
            try:
                await message.delete()
            except discord.Forbidden:
                pass  # bot doesn't have Manage Messages here — just ignore
            except Exception:
                pass
            return

        # ── Auto-FAQ in the help channel ──────────────────────────────
        # Rule-based responder: matches keywords in the user's message
        # against a small knowledge base.  Rate-limited per user so we
        # don't spam a single member with repeated auto-replies.
        if (message.guild is not None
                and not message.author.bot
                and message.type == discord.MessageType.default
                and "-ayuda" in message.channel.name):
            # Always log for analytics; the reply itself is rate-limited
            # inside _maybe_answer_faq to avoid spamming a single user.
            await self._maybe_answer_faq(message)

        # DM only — ignore everything else in guilds.
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
                    "✓ Rol Donor restaurado.  ¡Gracias por seguir apoyando "
                    "DJ Tracks!"
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

    # ── Auto-FAQ (used from on_message in #ayuda) ─────────────────────────
    _faq_last_reply: dict[int, float] = {}     # user_id → unix ts
    _FAQ_COOLDOWN_SEC: float = 300              # 5 min per user

    def _faq_rate_limit_ok(self, user_id: int) -> bool:
        import time
        last = self._faq_last_reply.get(user_id, 0.0)
        now = time.time()
        if now - last < self._FAQ_COOLDOWN_SEC:
            return False
        self._faq_last_reply[user_id] = now
        return True

    async def _maybe_answer_faq(self, message: discord.Message) -> None:
        """Match the message against the FAQ knowledge base and reply if
        we find a canned answer.  Silent otherwise — better to let a mod
        handle unrecognised questions than reply with garbage."""
        try:
            from faq_responder import match as match_faq
            entry = match_faq(message.content)

            # Log every question we saw — matched or not — for the
            # weekly digest's "top unmatched questions" list.
            with contextlib.suppress(Exception):
                from app import db
                with db() as c:
                    c.execute(
                        "INSERT INTO faq_events "
                        "(user_id, username, message, matched_title, ts) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (str(message.author.id),
                         str(message.author),
                         message.content[:500],
                         entry.title if entry else None,
                         int(time.time())),
                    )

            if not entry:
                return
            # Rate-limit the reply (not the logging above).
            if not self._faq_rate_limit_ok(message.author.id):
                return
            embed = discord.Embed(
                title=f"💡  {entry.title}",
                description=entry.answer,
                color=ACCENT_COLOR,
            )
            embed.set_footer(
                text=("Respuesta automática · si no resuelve tu duda, "
                      "un mod te ayudará"))
            await message.reply(embed=embed, mention_author=False)
            log.info(f"[FAQ] auto-answered {message.author}: {entry.title}")
        except Exception as exc:
            log.warning(f"[FAQ] failed to auto-answer: {exc}")

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
        with contextlib.suppress(discord.Forbidden):
            await user.send(embed=embed)


# ── Bot instance + lifecycle ────────────────────────────────────────────────

_intents = discord.Intents.default()
_intents.message_content = True   # required to read DM content
_intents.members = True           # required to receive on_member_update

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


# ── Public donation announcer ──────────────────────────────────────────────
#
# Called from the Ko-fi webhook after we've processed the donation.  Posts a
# cyan embed to the KOFI_ANNOUNCE_CHANNEL_ID channel so the community sees
# donations rolling in — social proof + gratitude wall.
#
# Respects two privacy safeguards:
#   1. Ko-fi's own ``is_public`` flag: if the donor asked to stay anonymous
#      we skip the announcement entirely.
#   2. Discord snowflakes are stripped from the message field before
#      posting — that field is where donors paste their own Discord ID for
#      us to match, and we don't want to leak IDs to the whole channel.

async def announce_donation(*,
                             name:      str,
                             amount:    float,
                             currency:  str = "EUR",
                             message:   str = "",
                             is_public: bool = True) -> bool:
    """Post a public embed announcing a new donation.  Silent no-op when
    KOFI_ANNOUNCE_CHANNEL_ID is unset or the donor is anonymous."""
    if not KOFI_ANNOUNCE_CHANNEL_ID or not is_public:
        return False
    try:
        channel = bot.get_channel(KOFI_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            channel = await bot.fetch_channel(KOFI_ANNOUNCE_CHANNEL_ID)
        if channel is None:
            log.warning(f"[Bot] announce channel {KOFI_ANNOUNCE_CHANNEL_ID} "
                        f"not found — skipping")
            return False

        symbol = _CURRENCY_SYMBOLS.get(currency.upper(), currency)
        embed = discord.Embed(
            title="💎  ¡Nueva donación!",
            color=ACCENT_COLOR,
            description="¡Gracias por hacer DJ Tracks posible! 🎧",
        )
        embed.add_field(name="Donante",
                        value=f"**{name.strip() or 'Anónimo'}**",
                        inline=True)
        embed.add_field(name="Importe",
                        value=f"**{amount:.2f}{symbol}**",
                        inline=True)

        # Optional message from the donor — stripped of any Discord ID
        # they might have pasted (that's for us, not the world).
        clean = _SNOWFLAKE_STRIP_RE.sub("", message or "").strip()
        # Also collapse whitespace left over from stripping the ID.
        clean = re.sub(r"\s{2,}", " ", clean).strip(" .,:;-—")
        if clean and len(clean) > 2:
            embed.add_field(name="Mensaje",
                            value=f"_{clean[:300]}_",
                            inline=False)

        embed.set_footer(text="DJ Tracks · Ko-fi")

        await channel.send(embed=embed)
        log.info(f"[Bot] Donation announced: {name} · {amount}{symbol}")
        return True
    except discord.Forbidden:
        log.warning(f"[Bot] no permission to post in channel "
                    f"{KOFI_ANNOUNCE_CHANNEL_ID}")
        return False
    except Exception as exc:
        log.error(f"[Bot] announce donation failed: {exc}")
        return False
