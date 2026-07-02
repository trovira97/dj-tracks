"""
scripts/setup_discord_server.py
================================
One-shot script that turns an empty Discord server into the full
DJ Tracks community layout described in docs/DISCORD_SERVER_SETUP.md.

Creates:
  * 8 roles (Owner / Moderador / Beta Tester / DJ Verified / Donor /
    Bug Hunter + notification roles) with the right colours and
    permissions, ordered so the bots sit above ``Donor``.
  * 7 categories with permission overwrites (Donors and Staff private).
  * ~30 channels with descriptive topics + slowmode where it matters.
  * Pinned welcome / rules / FAQ / bug-report messages.

Idempotent — running it twice **does not** duplicate anything.  It
inspects the current server, only creates what's missing, and leaves
untouched what already exists.

Requires (all read from ``backend/.env``):
  DISCORD_BOT_TOKEN
  DISCORD_GUILD_ID

Run from the repo root:

    python -m pip install discord.py python-dotenv
    python scripts/setup_discord_server.py
"""
from __future__ import annotations

import asyncio
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path

# ── Load .env from backend/ so we don't repeat the secrets ─────────────────
try:
    from dotenv import load_dotenv  # type: ignore[import-not-found]
    load_dotenv(Path(__file__).parent.parent / "backend" / ".env")
except ImportError:
    print("python-dotenv missing.  Run:  python -m pip install python-dotenv")
    sys.exit(1)

try:
    import discord
except ImportError:
    print("discord.py missing.  Run:  python -m pip install discord.py")
    sys.exit(1)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-5s %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("setup")

TOKEN    = os.environ.get("DISCORD_BOT_TOKEN")
GUILD_ID = int(os.environ.get("DISCORD_GUILD_ID", "0") or "0")

if not TOKEN or not GUILD_ID:
    log.error("DISCORD_BOT_TOKEN and DISCORD_GUILD_ID must be set in backend/.env")
    sys.exit(1)


# ── Design data — mirrors docs/DISCORD_SERVER_SETUP.md ─────────────────────

@dataclass
class RoleSpec:
    name:        str
    color:       int
    permissions: discord.Permissions = field(
        default_factory=lambda: discord.Permissions.none())
    mentionable: bool = False
    hoist:       bool = False


@dataclass
class ChannelSpec:
    name:      str
    topic:     str = ""
    slowmode:  int = 0                # seconds
    channel_type: discord.ChannelType = discord.ChannelType.text
    read_only: bool = False           # @everyone can't send messages
    pinned_message: str = ""          # optional first message to send + pin


@dataclass
class CategorySpec:
    name:    str
    channels: list[ChannelSpec]
    private_roles: list[str] = field(default_factory=list)
    # If private_roles is set, @everyone cannot view; only these roles can.


# Colours — from the app palette.
C_CYAN   = 0x00C8FF
C_RED    = 0xEF4444
C_GREEN  = 0x00FFB9
C_YELLOW = 0xFACC15
C_PURPLE = 0xA020FF
C_ORANGE = 0xFF6B00
C_MUTED  = 0x71717A

ROLES: list[RoleSpec] = [
    RoleSpec("Owner",         C_CYAN,
             discord.Permissions(administrator=True),
             mentionable=True, hoist=True),
    RoleSpec("Moderador",     C_RED,
             discord.Permissions(kick_members=True, ban_members=True,
                                 manage_messages=True, moderate_members=True,
                                 mute_members=True, view_audit_log=True),
             mentionable=True, hoist=True),
    RoleSpec("Beta Tester",   C_YELLOW, mentionable=True, hoist=True),
    RoleSpec("DJ Verified",   C_PURPLE, mentionable=True, hoist=True),
    RoleSpec("Donor",         C_GREEN,  mentionable=True, hoist=True),
    RoleSpec("Bug Hunter",    C_ORANGE, mentionable=True, hoist=True),
    RoleSpec("Notif Releases", C_MUTED, mentionable=True, hoist=False),
    RoleSpec("Notif Eventos",  C_MUTED, mentionable=True, hoist=False),
]

CATEGORIES: list[CategorySpec] = [
    CategorySpec("📢 INFORMACIÓN", [
        ChannelSpec("👋-bienvenida", topic="Bienvenida y presentación del server.",
                    read_only=True, pinned_message=(
                        "🎧 **¡Bienvenido a DJ Tracks!**\n\n"
                        "Somos la comunidad de la app open-source para descargar música "
                        "con metadatos Beatport (BPM, key, Camelot).\n\n"
                        "**Aquí puedes:**\n"
                        "✅ Pedir ayuda con la app\n"
                        "✅ Reportar bugs / sugerir features\n"
                        "✅ Compartir tracks y sets\n"
                        "✅ Acceder al canal exclusivo si donas\n\n"
                        "⚡ Empieza por leer **#📜-reglas** y pásate por **#🙋-ayuda** "
                        "si tienes dudas.\n\n"
                        "📦 Descarga: https://github.com/trovira97/dj-tracks/releases/latest\n"
                        "☕ Apoya el proyecto: https://ko-fi.com/trovira_97"
                    )),
        ChannelSpec("📜-reglas", topic="Reglas de la comunidad.",
                    read_only=True, pinned_message=(
                        "**📜 REGLAS DE LA COMUNIDAD**\n\n"
                        "**1. Respeto ante todo.** No toleramos insultos, acoso, "
                        "racismo, sexismo, homofobia ni discurso de odio.\n\n"
                        "**2. Nada de piratería a la vista.** La app se usa para casos "
                        "legítimos.  No compartas material bajo copyright ni links de "
                        "descarga ilegales aquí.\n\n"
                        "**3. No spam ni autopromoción agresiva.** Compartir tu música "
                        "es bienvenido en los canales musicales — publicidad constante "
                        "no.\n\n"
                        "**4. Un canal, un tema.** Cada canal tiene su propósito.  Léelo "
                        "en la descripción antes de postear.\n\n"
                        "**5. NSFW no.** Este es un server general.\n\n"
                        "**6. Nada de DMs no solicitados.** Si alguien lo hace, avisa a "
                        "un @Moderador.\n\n"
                        "**7. Cumple el ToS de Discord** — https://discord.com/terms\n\n"
                        "Incumplimiento = warning → mute → kick → ban, según gravedad."
                    )),
        ChannelSpec("📢-anuncios", topic="Anuncios oficiales del proyecto.",
                    read_only=True),
        ChannelSpec("🆕-changelog", topic="Feed automático de nuevas releases.",
                    read_only=True),
        ChannelSpec("❓-faq", topic="Preguntas frecuentes.",
                    read_only=True, pinned_message=(
                        "**❓ PREGUNTAS FRECUENTES**\n\n"
                        "**▪️ SmartScreen me avisa al abrir el .exe**\n"
                        "Es normal — la app no está firmada digitalmente todavía.\n"
                        "\"Más información\" → \"Ejecutar de todas formas\".\n\n"
                        "**▪️ ¿Cómo dono para desbloquear la app?**\n"
                        "Escríbele `!donate <€>` al bot DJ Tracks Bot por DM.\n"
                        "Te devuelve un enlace Ko-fi con tu Discord ID listo para pegar.\n\n"
                        "**▪️ Doné pero no tengo el rol**\n"
                        "- Espera 30 segundos\n"
                        "- Si nada, escribe `!fixrole` al bot\n"
                        "- Si sigue sin funcionar, pregunta en el canal de ayuda\n\n"
                        "**▪️ ¿Cómo configuro Spotify?**\n"
                        "Botón \"❓ ¿Cómo configurar Spotify?\" dentro de Ajustes,\n"
                        "o la guía completa: https://github.com/trovira97/dj-tracks\n\n"
                        "**▪️ La app se colgó / algo raro**\n"
                        "Ve al panel LOGS → filtra por ERROR → copia y pega en el "
                        "canal de bugs."
                    )),
    ]),
    CategorySpec("🎧 DJ TRACKS", [
        ChannelSpec("💬-general", topic="Chat general de la comunidad."),
        ChannelSpec("🙋-ayuda",   topic="Pide ayuda con la app: instalación, uso, errores."),
        ChannelSpec("💡-ideas",   topic="Sugerencias de features nuevas.  Reacciones para votar."),
        ChannelSpec("🐛-bugs",    topic="Reporta bugs (idealmente vía GitHub Issues).",
                    pinned_message=(
                        "**🐛 CÓMO REPORTAR UN BUG**\n\n"
                        "Los bugs se gestionan en GitHub Issues:\n"
                        "→ https://github.com/trovira97/dj-tracks/issues/new/choose\n\n"
                        "**Copia estos datos en el issue** (no aquí):\n"
                        "1. Versión de la app (Ajustes → arriba a la derecha)\n"
                        "2. Sistema operativo (Windows 10/11/…)\n"
                        "3. Qué hiciste, paso a paso\n"
                        "4. Qué esperabas que pasase\n"
                        "5. Qué pasó en su lugar\n"
                        "6. Logs: panel LOGS de la app → filtra ERROR → 📋 Copiar todo"
                    )),
        ChannelSpec("🌐-off-topic", topic="Todo lo que no sea sobre DJ Tracks."),
    ]),
    CategorySpec("🎵 MÚSICA", [
        ChannelSpec("🎶-descubrimientos", topic="Comparte tracks nuevos que hayas encontrado."),
        ChannelSpec("🎧-mis-sets",       topic="Postea tu set / mixtape reciente.", slowmode=3600),
        ChannelSpec("📀-playlists",       topic="Comparte playlists de Spotify/Apple/SoundCloud."),
        ChannelSpec("🔥-wip",             topic="Work in progress: producciones, edits.", slowmode=1800),
        ChannelSpec("🎤-request",         topic="\"¿Cómo se llama esta canción?\" — resolución colaborativa."),
    ]),
    CategorySpec("💎 DONORS", [
        ChannelSpec("🎉-donors-only",     topic="Chat exclusivo para donantes."),
        ChannelSpec("💾-beta-downloads",  topic="Enlaces a builds beta antes de release oficial."),
        ChannelSpec("🔮-roadmap",         topic="Discusión del roadmap privado."),
        ChannelSpec("🎁-perks",           topic="Cupones / recursos / packs exclusivos."),
        ChannelSpec("☕-thank-you",       topic="Muro de agradecimientos a donantes."),
    ], private_roles=["Donor", "Moderador", "Owner"]),
    CategorySpec("🛠️ DEV", [
        ChannelSpec("⚙️-desarrollo",     topic="Discusión técnica: features, arquitectura."),
        ChannelSpec("🧪-beta-testing",   topic="Coordinación de testing pre-release."),
        ChannelSpec("🔗-github-feed",    topic="Feed webhook de GitHub.", read_only=True),
        ChannelSpec("💻-plugins",        topic="Discusión sobre plugins/extensiones futuras."),
    ]),
    CategorySpec("🎉 CELEBRACIÓN", [
        ChannelSpec("🎉-nuevas-donaciones",
                    topic="Anuncios automáticos de nuevas donaciones.",
                    read_only=True),
    ]),
    CategorySpec("🎙️ VOZ", [
        ChannelSpec("🔊 General",     channel_type=discord.ChannelType.voice),
        ChannelSpec("🎧 Music Chill", channel_type=discord.ChannelType.voice),
        ChannelSpec("🎤 DJ Booth",    channel_type=discord.ChannelType.voice),
        ChannelSpec("🔇 Zzz · AFK",   channel_type=discord.ChannelType.voice),
    ]),
    CategorySpec("🔒 STAFF", [
        ChannelSpec("🛡️-mod-chat",  topic="Coordinación entre mods."),
        ChannelSpec("📋-mod-log",   topic="Log de acciones de moderación."),
        ChannelSpec("🔒-secretos",  topic="Discusiones sensibles."),
    ], private_roles=["Moderador", "Owner"]),
]


# ── Setup client ───────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.guilds  = True
intents.members = True

client = discord.Client(intents=intents)

created_roles:      dict[str, discord.Role]         = {}
created_categories: dict[str, discord.CategoryChannel] = {}
counters = {"roles": 0, "cats": 0, "chans": 0, "pins": 0, "skipped": 0}


async def ensure_role(guild: discord.Guild, spec: RoleSpec) -> discord.Role:
    """Return the existing role by name, or create it."""
    existing = discord.utils.get(guild.roles, name=spec.name)
    if existing:
        created_roles[spec.name] = existing
        counters["skipped"] += 1
        log.info(f"  · role  present  {spec.name}")
        return existing
    role = await guild.create_role(
        name        = spec.name,
        colour      = discord.Colour(spec.color),
        permissions = spec.permissions,
        mentionable = spec.mentionable,
        hoist       = spec.hoist,
        reason      = "DJ Tracks server bootstrap",
    )
    created_roles[spec.name] = role
    counters["roles"] += 1
    log.info(f"  ✓ role  created  {spec.name}")
    return role


async def ensure_category(guild: discord.Guild,
                          spec: CategorySpec) -> discord.CategoryChannel:
    """Create the category with permission overwrites; return existing if found."""
    existing = discord.utils.get(guild.categories, name=spec.name)
    if existing:
        created_categories[spec.name] = existing
        counters["skipped"] += 1
        log.info(f"cat   present  {spec.name}")
        return existing

    overwrites: dict = {}
    if spec.private_roles:
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            view_channel=False)
        for role_name in spec.private_roles:
            r = created_roles.get(role_name) or discord.utils.get(
                guild.roles, name=role_name)
            if r:
                overwrites[r] = discord.PermissionOverwrite(view_channel=True)

    cat = await guild.create_category(
        name       = spec.name,
        overwrites = overwrites,
        reason     = "DJ Tracks server bootstrap",
    )
    created_categories[spec.name] = cat
    counters["cats"] += 1
    log.info(f"cat   created  {spec.name}")
    return cat


async def ensure_channel(guild: discord.Guild,
                         cat:   discord.CategoryChannel,
                         spec:  ChannelSpec) -> discord.abc.GuildChannel:
    """Create the channel (or return existing).  Sends + pins the welcome
    message on the first run."""
    for ch in cat.channels:
        if ch.name.lower().strip("#") == spec.name.lower().strip("#"):
            counters["skipped"] += 1
            log.info(f"  · chan present  {spec.name}")
            return ch

    overwrites: dict = {}
    if spec.read_only:
        overwrites[guild.default_role] = discord.PermissionOverwrite(
            send_messages=False,
            add_reactions=True,
            read_messages=True,
        )

    kwargs: dict = {"category": cat, "overwrites": overwrites,
                    "reason": "DJ Tracks server bootstrap"}
    if spec.topic:
        kwargs["topic"] = spec.topic

    if spec.channel_type == discord.ChannelType.voice:
        chan = await guild.create_voice_channel(spec.name, **kwargs)
    else:
        if spec.slowmode:
            kwargs["slowmode_delay"] = spec.slowmode
        chan = await guild.create_text_channel(spec.name, **kwargs)

    counters["chans"] += 1
    log.info(f"  ✓ chan created  {spec.name}")

    if spec.pinned_message and isinstance(chan, discord.TextChannel):
        try:
            msg = await chan.send(spec.pinned_message)
            await msg.pin(reason="Welcome pin")
            counters["pins"] += 1
        except Exception as exc:
            log.warning(f"    ! could not pin welcome message: {exc}")

    return chan


async def reorder_roles(guild: discord.Guild) -> None:
    """Push the bot's own role above the Donor role so it can grant it.
    Discord orders roles bottom-up; higher position = more authority."""
    donor = created_roles.get("Donor") or discord.utils.get(guild.roles, name="Donor")
    if not donor:
        return
    try:
        me = guild.me
        if not me or not me.top_role:
            return
        if me.top_role.position <= donor.position:
            # Move bot's top role above Donor.
            positions = {me.top_role: donor.position + 1}
            await guild.edit_role_positions(positions=positions,
                                             reason="Bootstrap ordering")
            log.info(f"  ✓ moved bot role above Donor")
    except discord.Forbidden:
        log.warning("  ! can't reorder roles (missing Manage Roles?)")
    except Exception as exc:
        log.warning(f"  ! reorder failed: {exc}")


@client.event
async def on_ready() -> None:
    log.info(f"Connected as {client.user}")
    guild = client.get_guild(GUILD_ID)
    if guild is None:
        try:
            guild = await client.fetch_guild(GUILD_ID)
        except Exception:
            log.error(f"Guild {GUILD_ID} not found — is the bot in the server?")
            await client.close()
            return

    log.info(f"Target guild: {guild.name}")

    log.info("--- Roles ---")
    for spec in ROLES:
        await ensure_role(guild, spec)
    await reorder_roles(guild)

    log.info("--- Categories & channels ---")
    for cat_spec in CATEGORIES:
        cat = await ensure_category(guild, cat_spec)
        for chan_spec in cat_spec.channels:
            await ensure_channel(guild, cat, chan_spec)

    log.info("")
    log.info("─" * 60)
    log.info(f"  Roles created:      {counters['roles']}")
    log.info(f"  Categories created: {counters['cats']}")
    log.info(f"  Channels created:   {counters['chans']}")
    log.info(f"  Pinned messages:    {counters['pins']}")
    log.info(f"  Already existed:    {counters['skipped']}")
    log.info("─" * 60)
    log.info("")
    log.info("Manual follow-ups (Discord API doesn't cover these):")
    log.info("  • Enable Community mode (Settings → Community)")
    log.info("  • Configure Onboarding questions")
    log.info("  • Set the Welcome Screen (5 featured channels)")
    log.info("  • Boost target: 7 boosts to reach Level 1")
    log.info("  • Install a moderation bot (Wick recommended)")

    await client.close()


if __name__ == "__main__":
    try:
        asyncio.run(client.start(TOKEN))
    except KeyboardInterrupt:
        pass
    except discord.PrivilegedIntentsRequired:
        log.error("Enable SERVER MEMBERS INTENT in the Discord Developer Portal.")
        sys.exit(1)
