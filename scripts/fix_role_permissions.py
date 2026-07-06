"""
scripts/fix_role_permissions.py
==================================
Audit + correct server-level permissions per role.

Principles applied
------------------
- **@everyone**: minimal (view + read history + join public voice).  All
  interactions gated behind ``@Miembro``.
- **@Miembro**: standard "verified user" — chat + voice + reactions +
  application commands.
- **@Beta Tester / DJ Verified / Bug Hunter / Notif Releases /
  Notif Eventos / Donor / Miembro Activo / Regular / Veterano /
  Leyenda**: cosmetic-only, zero server-level perms.  Any extra access
  they need is granted via per-channel overrides (already done for
  Donor's private channels).
- **@Moderador**: ability to moderate — kick, timeout, delete
  messages, manage threads, mute/move in voice, view audit log.  NO
  ban (admin-only), NO manage roles/channels/guild.
- **@Owner**: full administrator.
- **Bots (@Koya, @DJ Tracks Bot, @Ko-fi Bot)**: left untouched — they
  set their own permissions when invited.

Print diff before applying; don't touch managed (integration) roles.
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
    format="%(message)s",
)
log = logging.getLogger("fix_role_perms")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])


# ── Desired permissions per role ──────────────────────────────────────────

def _perms_everyone() -> discord.Permissions:
    """@everyone: can see channels + hear voice.  No interaction."""
    p = discord.Permissions.none()
    p.view_channel         = True
    p.read_message_history = True
    p.connect              = True   # can enter voice to listen
    return p


def _perms_miembro() -> discord.Permissions:
    """@Miembro: standard verified user."""
    p = discord.Permissions.none()
    # General
    p.view_channel        = True
    p.change_nickname     = True
    p.create_instant_invite = True
    # Text
    p.send_messages           = True
    p.send_messages_in_threads = True
    p.create_public_threads    = True
    p.embed_links             = True
    p.attach_files            = True
    p.add_reactions           = True
    p.use_external_emojis     = True
    p.use_external_stickers   = True
    p.read_message_history    = True
    p.use_application_commands = True
    p.send_polls              = True
    # Voice
    p.connect              = True
    p.speak                = True
    p.stream               = True
    p.use_voice_activation = True
    p.use_soundboard       = True
    # Events
    p.create_events        = True
    p.use_embedded_activities = True
    return p


def _perms_cosmetic() -> discord.Permissions:
    """Tag-only roles (Donor, milestones, notif, DJ Verified, etc.).
    Server-level perms: none — everything inherited from @Miembro."""
    return discord.Permissions.none()


def _perms_moderador() -> discord.Permissions:
    """@Moderador: everything a mod needs, nothing that could nuke the server."""
    p = _perms_miembro()               # includes chat + voice
    # Moderation
    p.kick_members         = True
    p.moderate_members     = True     # timeout
    p.manage_messages      = True
    p.manage_threads       = True
    p.mute_members         = True
    p.deafen_members       = True
    p.move_members         = True
    p.view_audit_log       = True
    p.mention_everyone     = True     # for announcements
    p.priority_speaker     = True     # for voice moderation
    # Explicitly NOT granted: ban_members, administrator, manage_roles,
    # manage_channels, manage_guild, manage_webhooks, manage_emojis
    return p


def _perms_owner() -> discord.Permissions:
    """@Owner: full admin."""
    p = discord.Permissions.all()
    return p


DESIRED: dict[str, discord.Permissions] = {
    "@everyone":        _perms_everyone(),
    "Miembro":          _perms_miembro(),
    "Beta Tester":      _perms_cosmetic(),
    "DJ Verified":      _perms_cosmetic(),
    "Bug Hunter":       _perms_cosmetic(),
    "Notif Releases":   _perms_cosmetic(),
    "Notif Eventos":    _perms_cosmetic(),
    "Miembro Activo":   _perms_cosmetic(),
    "Regular":          _perms_cosmetic(),
    "Veterano":         _perms_cosmetic(),
    "Leyenda":          _perms_cosmetic(),
    "Donor":            _perms_cosmetic(),
    "Moderador":        _perms_moderador(),
    "Owner":            _perms_owner(),
}


# ── Runner ────────────────────────────────────────────────────────────────

def _diff_perms(current: discord.Permissions,
                desired: discord.Permissions) -> tuple[list[str], list[str]]:
    """Return (perms_to_grant, perms_to_revoke)."""
    cur = {name for name, val in current if val}
    des = {name for name, val in desired if val}
    return sorted(des - cur), sorted(cur - des)


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

        log.info("=" * 76)
        log.info(f"ROLE PERMISSIONS AUDIT · {guild.name}")
        log.info("=" * 76)

        changes = 0
        for name, desired in DESIRED.items():
            if name == "@everyone":
                role = guild.default_role
            else:
                role = discord.utils.get(guild.roles, name=name)
            if role is None:
                log.info(f"  ! @{name}: NOT FOUND (skip)")
                continue
            if role.managed:
                log.info(f"  ~ @{name}: managed by integration (skip)")
                continue

            grant, revoke = _diff_perms(role.permissions, desired)
            if not grant and not revoke:
                log.info(f"  ✓ @{name}: already correct")
                continue

            log.info(f"  ⚙ @{name}:")
            if grant:
                log.info(f"      + grant : {', '.join(grant)}")
            if revoke:
                log.info(f"      - revoke: {', '.join(revoke)}")

            try:
                await role.edit(permissions=desired,
                                reason="Least-privilege audit")
                changes += 1
                log.info(f"      → applied")
            except discord.Forbidden:
                log.info(f"      ! Forbidden — hierarchy or bot perms")
            except Exception as exc:
                log.info(f"      ! failed: {exc}")

        log.info("")
        log.info(f"Applied {changes} role permission update(s).")


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
