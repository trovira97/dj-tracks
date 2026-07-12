# scripts/discord/

Server-maintenance one-shots for the DJ Tracks Discord.  These are
**not** part of the app or the bot runtime — they're standalone
Python scripts you invoke by hand when you need to (re)build a
piece of the server layout, patch permissions, or grant a role.

## How to run

Every script expects the same env vars as `backend/bot.py`:

```bash
DISCORD_BOT_TOKEN=...
DISCORD_GUILD_ID=...
# some scripts also need DISCORD_DONOR_ROLE_ID or similar
```

From the repo root:

```bash
py -m scripts.discord.<name>            # e.g. scripts.discord.audit_server
```

## Categories

**Full setup (idempotent)** — run once on a fresh server:
- `setup_discord_server.py` — creates the 8 categories, 32 channels,
  8 roles, and applies the permission matrix.
- `create_milestone_roles.py`, `create_roles_channel.py`,
  `create_voice_hub.py`, `create_honeypot_channel.py`,
  `create_mod_log_channel.py` — carve out specific pieces if you're
  bootstrapping a new server incrementally.

**Fixes** — run when something drifts:
- `fix_role_permissions.py` — reapply the canonical permission matrix.
- `fix_milestone_hierarchy.py` — reorder milestone roles by level.
- `fix_voice_hub.py` — repair the temp-voice-channel machinery.
- `grant_koya_voice_view.py` — one-off permission grant.

**Utilities** — safe to run any time:
- `audit_server.py` — read-only sanity check of the server state.
- `add_official_links.py` — pin the "Enlaces oficiales" embed in
  `#👋-bienvenida`.
- `open_trigger_channel.py` — expose a specific channel to @everyone.
