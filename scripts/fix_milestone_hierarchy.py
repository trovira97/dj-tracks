"""
scripts/fix_milestone_hierarchy.py
====================================
Reorder the 4 milestone roles so higher-tier = higher position:

    Koya  (unchanged)
    Leyenda        ← highest milestone
    Veterano
    Regular
    Miembro Activo ← lowest milestone
    …other roles…

Discord orders roles bottom-up (position 1 = lowest), so higher-tier
milestones need larger position numbers.  Since `create_milestone_roles.py`
placed them all just below Koya but Discord's role.edit(position=...) API
processes them in an order that ends up inverted, we correct here.
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
log = logging.getLogger("fix_milestone_hierarchy")


TOKEN    = os.environ["DISCORD_BOT_TOKEN"]
GUILD_ID = int(os.environ["DISCORD_GUILD_ID"])

# Ordered lowest → highest tier.  Reversed when placing.
MILESTONE_NAMES = ["Miembro Activo", "Regular", "Veterano", "Leyenda"]


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
        log.info(f"Koya position: {koya.position}")

        roles = {name: discord.utils.get(guild.roles, name=name)
                 for name in MILESTONE_NAMES}
        for name, r in roles.items():
            if r is None:
                log.error(f"Role @{name} not found — abort")
                return

        # Use bulk-edit via guild.edit_role_positions — sets absolute
        # positions in one API call, avoids the reordering-during-writes
        # bug of individual role.edit(position=).
        #
        # Positions: Leyenda closest to Koya, Miembro Activo lowest.
        # Koya = P → Leyenda = P-1, Veterano = P-2, Regular = P-3,
        # Miembro Activo = P-4.
        base = koya.position - 1
        positions = {
            roles["Leyenda"]:        base,
            roles["Veterano"]:       base - 1,
            roles["Regular"]:        base - 2,
            roles["Miembro Activo"]: base - 3,
        }
        try:
            await guild.edit_role_positions(positions=positions,
                                            reason="Fix milestone hierarchy")
            log.info("Reordered milestones:")
            for r, p in positions.items():
                log.info(f"  #{p:2}  @{r.name}")
        except discord.Forbidden:
            log.error("Manage Roles missing — can't reorder")
        except Exception as exc:
            log.error(f"Failed: {exc}")


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
