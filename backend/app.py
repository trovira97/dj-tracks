"""
backend/app.py
===============
DJ Tracks backend — Discord role verification + Ko-fi webhook receiver.

Endpoints
---------
GET  /                  health check
GET  /verify            { discord_id } -> { donor: bool }
GET  /discord/start     { token }      -> 302 redirect to Discord OAuth
GET  /discord/callback  Discord redirects here after user consent;
                        we record the result keyed by the original token
                        so the desktop app can pick it up via poll.
GET  /discord/poll      { token }      -> 200 with result | 202 pending
POST /kofi-webhook                     Ko-fi signed JSON → assign role +
                                       remember the donor's email so we
                                       can match a later Discord link.

Required environment variables (see .env.example):
    DISCORD_CLIENT_ID, DISCORD_CLIENT_SECRET, DISCORD_BOT_TOKEN,
    DISCORD_GUILD_ID, DISCORD_DONOR_ROLE_ID, DISCORD_REDIRECT_URI,
    KOFI_VERIFICATION_TOKEN

Run locally:
    uvicorn backend.app:app --port 8732 --reload
"""
from __future__ import annotations

import json
import logging
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Optional

import httpx
from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from pydantic import BaseModel

log = logging.getLogger("dj_tracks.backend")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")

# ── Config ──────────────────────────────────────────────────────────────────

DISCORD_CLIENT_ID     = os.environ["DISCORD_CLIENT_ID"]
DISCORD_CLIENT_SECRET = os.environ["DISCORD_CLIENT_SECRET"]
DISCORD_BOT_TOKEN     = os.environ["DISCORD_BOT_TOKEN"]
DISCORD_GUILD_ID      = os.environ["DISCORD_GUILD_ID"]
DISCORD_DONOR_ROLE_ID = os.environ["DISCORD_DONOR_ROLE_ID"]
DISCORD_REDIRECT_URI  = os.environ.get(
    "DISCORD_REDIRECT_URI",
    "http://localhost:8732/discord/callback",
)
KOFI_VERIFICATION_TOKEN = os.environ["KOFI_VERIFICATION_TOKEN"]

DB_PATH = Path(os.environ.get("DB_PATH", "donors.db"))

DISCORD_API = "https://discord.com/api/v10"


# ── Storage ─────────────────────────────────────────────────────────────────

@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


FREE_LIMIT = 10


def init_db() -> None:
    with db() as c:
        c.executescript("""
            CREATE TABLE IF NOT EXISTS donors (
                discord_id  TEXT PRIMARY KEY,
                username    TEXT,
                email       TEXT,
                amount      REAL,
                first_seen  INTEGER,
                last_seen   INTEGER
            );
            CREATE TABLE IF NOT EXISTS pending_donations (
                email       TEXT PRIMARY KEY,
                amount      REAL,
                received    INTEGER
            );
            CREATE TABLE IF NOT EXISTS oauth_results (
                token            TEXT PRIMARY KEY,
                created          INTEGER,
                discord_user_id  TEXT,
                discord_username TEXT,
                donor            INTEGER
            );
            -- Per-device usage counter.  The server is the source of
            -- truth — clients can't pretend they haven't downloaded by
            -- editing their local file.
            CREATE TABLE IF NOT EXISTS usage (
                device_id      TEXT PRIMARY KEY,
                discord_id     TEXT,
                download_count INTEGER DEFAULT 0,
                first_seen     INTEGER,
                last_seen      INTEGER
            );
            CREATE INDEX IF NOT EXISTS idx_oauth_created
                ON oauth_results(created);
            CREATE INDEX IF NOT EXISTS idx_donors_email
                ON donors(email);
            CREATE INDEX IF NOT EXISTS idx_usage_discord
                ON usage(discord_id);
        """)


def _is_donor_id(discord_id: str) -> bool:
    """Quick CACHE-ONLY check: is this discord_id in the donors table?

    Doesn't hit Discord — for the live-fallback variant that catches
    manually-assigned roles, use _check_donor_status().
    """
    if not discord_id:
        return False
    with db() as c:
        row = c.execute("SELECT 1 FROM donors WHERE discord_id = ?",
                        (discord_id,)).fetchone()
    return bool(row)


async def _check_donor_status(discord_id: str) -> bool:
    """Cached check + live Discord fallback.

    Catches the case where the admin manually grants the Donor role
    to a friend in Discord — our DB doesn't know yet, so on the next
    /usage/check we ask Discord directly.  If they hold the role, we
    persist them in the donors table so the next check is fast.
    """
    if not discord_id:
        return False
    if _is_donor_id(discord_id):
        return True
    has_role = await discord_member_has_role(discord_id)
    if has_role:
        now = int(time.time())
        with db() as c:
            c.execute("INSERT OR IGNORE INTO donors "
                      "(discord_id, first_seen, last_seen) "
                      "VALUES (?, ?, ?)",
                      (discord_id, now, now))
        log.info("[Donor] live role check caught manual grant: %s",
                 discord_id)
    return has_role


def _usage_row(device_id: str) -> dict:
    """Return the per-device usage state.  Creates a fresh row on first
    contact so the device starts at count=0."""
    now = int(time.time())
    with db() as c:
        row = c.execute(
            "SELECT device_id, discord_id, download_count "
            "FROM usage WHERE device_id = ?", (device_id,)).fetchone()
        if not row:
            c.execute(
                "INSERT INTO usage (device_id, download_count, "
                "first_seen, last_seen) VALUES (?, 0, ?, ?)",
                (device_id, now, now))
            return {"device_id": device_id, "discord_id": "",
                    "download_count": 0}
        c.execute("UPDATE usage SET last_seen = ? WHERE device_id = ?",
                  (now, device_id))
        return {"device_id":      row["device_id"],
                "discord_id":     row["discord_id"] or "",
                "download_count": int(row["download_count"] or 0)}


def _usage_summary(state: dict, is_donor: bool) -> dict:
    """Common response shape for /usage/* endpoints.  Caller supplies
    is_donor — usually from _check_donor_status() so the result is
    live-accurate."""
    count    = int(state.get("download_count", 0))
    remaining = -1 if is_donor else max(0, FREE_LIMIT - count)
    return {
        "device_id":      state["device_id"],
        "discord_id":     state.get("discord_id", ""),
        "download_count": count,
        "is_donor":       is_donor,
        "free_limit":     FREE_LIMIT,
        "remaining":      remaining,
        "allowed":        is_donor or count < FREE_LIMIT,
    }


# ── Discord REST helpers ───────────────────────────────────────────────────

async def discord_add_donor_role(discord_user_id: str) -> bool:
    """Assign the Donor role to *discord_user_id* in our guild."""
    url = (f"{DISCORD_API}/guilds/{DISCORD_GUILD_ID}"
           f"/members/{discord_user_id}/roles/{DISCORD_DONOR_ROLE_ID}")
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.put(url, headers={
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        })
    if r.status_code in (204, 200, 201):
        return True
    log.warning(f"[Discord] add role HTTP {r.status_code}: {r.text[:200]}")
    return False


async def discord_member_has_role(discord_user_id: str) -> bool:
    """Check whether *discord_user_id* currently holds the Donor role."""
    url = f"{DISCORD_API}/guilds/{DISCORD_GUILD_ID}/members/{discord_user_id}"
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(url, headers={
            "Authorization": f"Bot {DISCORD_BOT_TOKEN}",
        })
    if r.status_code != 200:
        return False
    roles = (r.json() or {}).get("roles") or []
    return DISCORD_DONOR_ROLE_ID in roles


# ── FastAPI app ────────────────────────────────────────────────────────────

app = FastAPI(title="DJ Tracks backend", version="1.0.0")


@app.on_event("startup")
async def _startup() -> None:
    init_db()
    log.info("[Startup] DB ready at %s", DB_PATH.resolve())
    # Launch the Discord bot as a background task on the same event
    # loop FastAPI is using.  asyncio.create_task() won't block startup
    # but lets the bot's gateway connection run forever alongside HTTP.
    import asyncio
    from bot import start_bot
    asyncio.create_task(start_bot())
    log.info("[Startup] Discord bot launched")


@app.on_event("shutdown")
async def _shutdown() -> None:
    try:
        from bot import stop_bot
        await stop_bot()
    except Exception as exc:
        log.warning(f"[Shutdown] bot stop failed: {exc}")


@app.get("/")
def health() -> dict:
    return {"ok": True, "service": "dj-tracks-backend"}


# ── Server-side freemium gate ──────────────────────────────────────────────

class UsageBody(BaseModel):
    device_id:  str
    discord_id: Optional[str] = None    # only meaningful on /usage/link


@app.post("/usage/check")
async def usage_check(body: UsageBody) -> dict:
    """Ask the server if this device may start a new download.

    Source of truth — the local app cannot lie about its counter.
    Donors get unlimited (remaining = -1).
    Uses _check_donor_status so manually-assigned roles are caught
    on the first check after the admin grants them in Discord.
    """
    if not body.device_id or len(body.device_id) < 8:
        raise HTTPException(400, "device_id required")
    state    = _usage_row(body.device_id)
    is_donor = await _check_donor_status(state.get("discord_id", ""))
    return _usage_summary(state, is_donor)


@app.post("/usage/record")
async def usage_record(body: UsageBody) -> dict:
    """Bump the per-device counter after a successful download.

    Donors are exempt (we still upsert the row so we can track usage
    metrics later, but we don't increment count).
    """
    if not body.device_id or len(body.device_id) < 8:
        raise HTTPException(400, "device_id required")
    state    = _usage_row(body.device_id)
    is_donor = await _check_donor_status(state.get("discord_id", ""))
    if not is_donor:
        new_count = int(state["download_count"]) + 1
        with db() as c:
            c.execute(
                "UPDATE usage SET download_count = ?, last_seen = ? "
                "WHERE device_id = ?",
                (new_count, int(time.time()), body.device_id))
        state["download_count"] = new_count
    return _usage_summary(state, is_donor)


@app.post("/usage/link")
async def usage_link(body: UsageBody) -> dict:
    """Bind a device to a Discord user (called after a successful
    OAuth so future /usage/check calls know the user is a donor)."""
    if not body.device_id or len(body.device_id) < 8:
        raise HTTPException(400, "device_id required")
    if not body.discord_id:
        raise HTTPException(400, "discord_id required for link")
    _usage_row(body.device_id)   # ensure row exists
    with db() as c:
        c.execute(
            "UPDATE usage SET discord_id = ?, last_seen = ? "
            "WHERE device_id = ?",
            (body.discord_id, int(time.time()), body.device_id))
    state    = _usage_row(body.device_id)
    is_donor = await _check_donor_status(state.get("discord_id", ""))
    return _usage_summary(state, is_donor)


# ── /verify — desktop app polls this ───────────────────────────────────────

@app.get("/verify")
async def verify(discord_id: str) -> dict:
    """Cached-then-live check.  If we have the user in our local donors
    table, return True without bothering Discord; otherwise hit Discord
    and cache the result.

    Returns: {"donor": bool}
    """
    if not discord_id:
        raise HTTPException(400, "discord_id required")
    with db() as c:
        row = c.execute("SELECT 1 FROM donors WHERE discord_id = ?",
                        (discord_id,)).fetchone()
    if row:
        return {"donor": True}
    # Not in our table — ask Discord (handles case where role was
    # assigned manually or via another channel).
    live = await discord_member_has_role(discord_id)
    if live:
        now = int(time.time())
        with db() as c:
            c.execute("INSERT OR IGNORE INTO donors "
                      "(discord_id, first_seen, last_seen) VALUES (?, ?, ?)",
                      (discord_id, now, now))
    return {"donor": bool(live)}


# ── /discord/start + /discord/callback + /discord/poll — OAuth flow ───────

@app.get("/discord/start")
def discord_start(token: str) -> RedirectResponse:
    """Redirect the user's browser to Discord's authorize page.  We
    forward *token* via the state parameter so the callback can match
    the result back to the desktop app's poll."""
    if not token or len(token) < 8:
        raise HTTPException(400, "token required")
    params = {
        "client_id":     DISCORD_CLIENT_ID,
        "response_type": "code",
        # "email" lets us match the donor to a Ko-fi donation by their
        # registered Discord email when the Ko-fi message field didn't
        # carry their Discord ID.
        "scope":         "identify email",
        "redirect_uri":  DISCORD_REDIRECT_URI,
        "state":         token,
        "prompt":        "none",
    }
    qs = "&".join(f"{k}={httpx.QueryParams({k: v}).get(k)}"
                  for k, v in params.items())
    return RedirectResponse(f"{DISCORD_API}/oauth2/authorize?{qs}")


@app.get("/discord/callback")
async def discord_callback(code: str, state: str) -> HTMLResponse:
    """Discord redirects here after user consent."""
    # 1) Exchange code → access token.
    async with httpx.AsyncClient(timeout=10) as client:
        token_r = await client.post(
            f"{DISCORD_API}/oauth2/token",
            data={
                "client_id":     DISCORD_CLIENT_ID,
                "client_secret": DISCORD_CLIENT_SECRET,
                "grant_type":    "authorization_code",
                "code":          code,
                "redirect_uri":  DISCORD_REDIRECT_URI,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        if token_r.status_code != 200:
            return HTMLResponse(_html_error("No pudimos validar el login."),
                                status_code=400)
        access_token = token_r.json().get("access_token")

        # 2) Fetch the user's identity (with the email scope we also
        #    get their registered Discord email — used to match Ko-fi
        #    donations stashed earlier under that same email).
        me_r = await client.get(f"{DISCORD_API}/users/@me", headers={
            "Authorization": f"Bearer {access_token}"})
        if me_r.status_code != 200:
            return HTMLResponse(_html_error("Discord no nos dio tu identidad."),
                                status_code=400)
        me = me_r.json()
        discord_id = me["id"]
        username   = me.get("username", "")
        email      = (me.get("email") or "").lower().strip()

    # 3) Already a donor (from our DB or from a previous role assignment)?
    is_donor = await _resolve_donor_status(discord_id, username, email)

    # 4) Persist the result keyed by the desktop app's poll token.
    now = int(time.time())
    with db() as c:
        c.execute(
            "INSERT OR REPLACE INTO oauth_results "
            "(token, created, discord_user_id, discord_username, donor) "
            "VALUES (?, ?, ?, ?, ?)",
            (state, now, discord_id, username, 1 if is_donor else 0),
        )
        # GC: prune anything older than 1 hour.
        c.execute("DELETE FROM oauth_results WHERE created < ?",
                  (now - 3600,))

    if is_donor:
        return HTMLResponse(_html_success(
            f"¡Bienvenido, {username}! Has sido verificado como Donor. "
            f"Cierra esta pestaña y vuelve a DJ Tracks."))
    return HTMLResponse(_html_pending(
        f"Hola {username}. Aún no constas como Donor. Si acabas de donar, "
        f"vuelve a DJ Tracks y pulsa el botón de nuevo en un par de minutos."))


@app.get("/discord/poll")
def discord_poll(token: str) -> JSONResponse:
    """Desktop app long-polls this until the OAuth flow finishes."""
    with db() as c:
        row = c.execute("SELECT discord_user_id, discord_username, donor "
                        "FROM oauth_results WHERE token = ?",
                        (token,)).fetchone()
    if not row:
        return JSONResponse({"pending": True}, status_code=202)
    return JSONResponse({
        "discord_user_id":  row["discord_user_id"],
        "discord_username": row["discord_username"],
        "donor":            bool(row["donor"]),
    })


# ── Ko-fi webhook ─────────────────────────────────────────────────────────

# A Discord snowflake is 17-19 digits long.  We look for the FIRST
# occurrence in the Ko-fi message; that's almost always the donor
# pasting their own User ID.
_SNOWFLAKE_RE = re.compile(r"\b(\d{17,20})\b")


@app.post("/kofi-webhook")
async def kofi_webhook(request: Request) -> dict:
    """Ko-fi POSTs form-encoded data with a single field `data` containing
    a JSON payload.  Three matching paths, tried in order:
      1. The donor pasted their Discord User ID in the message → assign
         the role to that ID directly (fastest, fully automatic).
      2. We already have that email linked to a Discord ID from a prior
         OAuth login → assign the role.
      3. Neither — stash in pending_donations so the NEXT OAuth flow
         from that email gets auto-approved.
    """
    form = await request.form()
    raw  = form.get("data") or "{}"
    try:
        payload = json.loads(raw)
    except Exception:
        raise HTTPException(400, "invalid payload")

    if payload.get("verification_token") != KOFI_VERIFICATION_TOKEN:
        log.warning("[Ko-fi] bad verification token — rejecting")
        raise HTTPException(401, "bad verification token")

    if payload.get("type") not in ("Donation", "Subscription"):
        return {"ignored": payload.get("type")}

    email   = (payload.get("email")   or "").lower().strip()
    amount  = float(payload.get("amount") or 0)
    message = (payload.get("message") or "").strip()

    # ── Path 1: Discord ID in the message ────────────────────────────
    m = _SNOWFLAKE_RE.search(message)
    if m:
        discord_id = m.group(1)
        ok = await discord_add_donor_role(discord_id)
        if ok:
            now = int(time.time())
            with db() as c:
                c.execute(
                    "INSERT OR REPLACE INTO donors "
                    "(discord_id, email, amount, first_seen, last_seen) "
                    "VALUES (?, ?, ?, "
                    "  COALESCE((SELECT first_seen FROM donors WHERE discord_id=?), ?), "
                    "  ?)",
                    (discord_id, email or None, amount,
                     discord_id, now, now))
            log.info("[Ko-fi] role assigned via message ID: %s", discord_id)
            return {"assigned": True, "method": "message_id",
                    "discord_id": discord_id}
        log.warning("[Ko-fi] could not assign role to %s — "
                    "user might not be in the guild yet", discord_id)
        # fall through to the email path

    # ── Path 2: email already linked from a prior OAuth ──────────────
    if email:
        with db() as c:
            donor = c.execute("SELECT discord_id FROM donors WHERE email = ?",
                              (email,)).fetchone()
        if donor:
            discord_id = donor["discord_id"]
            ok = await discord_add_donor_role(discord_id)
            log.info("[Ko-fi] role assigned via email match: %s -> %s",
                     email, discord_id)
            return {"assigned": ok, "method": "email_match",
                    "discord_id": discord_id}

    # ── Path 3: stash for the next OAuth ─────────────────────────────
    if email:
        with db() as c:
            c.execute("INSERT OR REPLACE INTO pending_donations "
                      "(email, amount, received) VALUES (?, ?, ?)",
                      (email, amount, int(time.time())))
        log.info("[Ko-fi] donation stashed for %s (%s €) "
                 "— waiting for OAuth", email, amount)
        return {"stashed": True, "email": email}

    log.warning("[Ko-fi] donation without email or Discord ID — "
                "no way to auto-grant.  Manual intervention required.")
    return {"orphan": True}


# ── Helpers ───────────────────────────────────────────────────────────────

async def _resolve_donor_status(discord_id: str, username: str,
                                email: str = "") -> bool:
    """Decide whether this Discord user should be granted donor status now.

    Four sources of truth, checked in order:
      1. They're in our donors table from a previous link (instant True).
      2. They already hold the role on Discord (admin assigned manually
         or a previous Ko-fi webhook used their User ID).
      3. There's a pending Ko-fi donation under their Discord email →
         claim it now: assign the role, remember the link, clear the
         pending row.
      4. Nothing — they're not a donor.
    """
    now = int(time.time())

    # 1) Already linked.
    with db() as c:
        row = c.execute("SELECT 1 FROM donors WHERE discord_id = ?",
                        (discord_id,)).fetchone()
    if row:
        return True

    # 2) Has the role already?
    has_role = await discord_member_has_role(discord_id)
    if has_role:
        with db() as c:
            c.execute("INSERT OR IGNORE INTO donors "
                      "(discord_id, username, email, first_seen, last_seen) "
                      "VALUES (?, ?, ?, ?, ?)",
                      (discord_id, username, email or None, now, now))
        return True

    # 3) Pending donation under their Discord email?
    if email:
        with db() as c:
            pending = c.execute(
                "SELECT amount FROM pending_donations WHERE email = ?",
                (email,)).fetchone()
        if pending:
            ok = await discord_add_donor_role(discord_id)
            if ok:
                with db() as c:
                    c.execute(
                        "INSERT OR REPLACE INTO donors "
                        "(discord_id, username, email, amount, "
                        " first_seen, last_seen) VALUES (?,?,?,?,?,?)",
                        (discord_id, username, email,
                         float(pending["amount"]), now, now))
                    c.execute("DELETE FROM pending_donations WHERE email = ?",
                              (email,))
                log.info("[OAuth] claimed pending donation %s → %s",
                         email, discord_id)
                return True
            log.warning("[OAuth] failed to assign role for %s after "
                        "matching pending donation", discord_id)

    # 4) Not a donor.
    return False


def _html_success(msg: str) -> str:
    return f"""
<!doctype html><html><head><meta charset="utf-8">
<title>DJ Tracks · Verificado</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #0B0B17;
          color: #E4E4E7; padding: 80px 20px; text-align: center; }}
  h1 {{ color: #00C8FF; font-size: 28px; margin-bottom: 16px; }}
  p {{ max-width: 480px; margin: 0 auto; line-height: 1.6; color: #A1A1AA; }}
</style></head><body>
<h1>✓ Verificado</h1><p>{msg}</p></body></html>
"""


def _html_pending(msg: str) -> str:
    return f"""
<!doctype html><html><head><meta charset="utf-8">
<title>DJ Tracks · Pendiente</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #0B0B17;
          color: #E4E4E7; padding: 80px 20px; text-align: center; }}
  h1 {{ color: #FACC15; font-size: 28px; margin-bottom: 16px; }}
  p {{ max-width: 480px; margin: 0 auto; line-height: 1.6; color: #A1A1AA; }}
</style></head><body>
<h1>⌛ Pendiente</h1><p>{msg}</p></body></html>
"""


def _html_error(msg: str) -> str:
    return f"""
<!doctype html><html><head><meta charset="utf-8">
<title>DJ Tracks · Error</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, sans-serif; background: #0B0B17;
          color: #E4E4E7; padding: 80px 20px; text-align: center; }}
  h1 {{ color: #EF4444; font-size: 28px; margin-bottom: 16px; }}
  p {{ max-width: 480px; margin: 0 auto; line-height: 1.6; color: #A1A1AA; }}
</style></head><body>
<h1>✕ Error</h1><p>{msg}</p></body></html>
"""
