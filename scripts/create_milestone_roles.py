"""
scripts/create_milestone_roles.py
==================================
One-shot: create the 4 XP-milestone roles used by Koya's Niveles module.

Roles:
    Miembro Activo   verde  (level 5)
    Regular          azul   (level 20)
    Veterano         oro    (level 50)
    Leyenda          rojo   (level 100)

They're placed **immediately below Koya** so Koya can assign/remove them,
but above @everyone.  Non-hoisted (no separate section in the sidebar) and
non-mentionable to keep the roles list clean.

Idempotent: existing roles keep their config, are just re-ordered if needed.

Usage:
    py scripts/create_milestone_roles.py
"""
from __future__ import annotations

import asyncio
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
log = logging.getLogger("create_milestone_roles")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

# name → colour (hex), ordered lowest-tier first
MILESTONES: list[tuple[str, int]] = [
    ("Miembro Activo", 0x7ED957),  # green
    ("Regular",        0x3498DB),  # blue
    ("Veterano",       0xF1C40F),  # gold
    ("Leyenda",        0xE74C3C),  # red
]


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
            log.warning("Koya role not found — will still create the roles, "
                        "but you'll have to place them under Koya manually.")

        created: list[discord.Role] = []
        for name, colour in MILESTONES:
            existing = discord.utils.get(guild.roles, name=name)
            if existing:
                log.info(f"Role @{name} already exists (id={existing.id}) — skipping")
                created.append(existing)
                continue
            try:
                role = await guild.create_role(
                    name=name,
                    colour=discord.Colour(colour),
                    hoist=False,          # don't list separately in sidebar
                    mentionable=False,
                    reason="Koya XP milestone role",
                )
                log.info(f"Created @{name} (id={role.id}, colour=#{colour:06X})")
                created.append(role)
            except Exception as exc:
                log.error(f"Failed to create @{name}: {exc}")

        # Try to place them right below Koya, preserving order.
        if koya is not None and created:
            target_pos = max(1, koya.position - 1)  # one below Koya
            # Move highest-tier (Leyenda) closest to Koya so hierarchy is
            # Koya > Leyenda > Veterano > Regular > Miembro Activo.
            for role in reversed(created):
                try:
                    await role.edit(position=target_pos, reason="Below Koya")
                except discord.Forbidden:
                    log.warning(f"Can't move @{role.name} — Manage Roles missing")
                    break
                except Exception as exc:
                    log.warning(f"Couldn't move @{role.name}: {exc}")

        log.info("")
        log.info("Next step — in the Koya dashboard → Niveles → Recompensas:")
        log.info("  Level 5   → @Miembro Activo")
        log.info("  Level 20  → @Regular")
        log.info("  Level 50  → @Veterano")
        log.info("  Level 100 → @Leyenda")


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
