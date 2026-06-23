"""
utils/donor_client.py
=====================
Thin HTTP client that talks to the DJ Tracks backend to verify donor
status and to start the Discord OAuth flow.

The backend lives in its own service (see ``backend/`` folder).  At
runtime the user's install only needs to know:
  - the backend base URL (set via DJ_TRACKS_BACKEND env var or the
    BACKEND_URL constant below)
  - the OAuth start URL (the backend tells the app where to send the
    user when they click "Conectar Discord")

Falls back to "not a donor" on any network error so the app never
hangs the lockout screen waiting for a server response.
"""
from __future__ import annotations

import logging
import os
import webbrowser

log = logging.getLogger("dj_tracks.donor.client")

# Default backend URL — overridden by env var DJ_TRACKS_BACKEND or by
# settings.json["backend_url"].  Set this to your deployed backend
# (Railway / Fly / etc.) before shipping.
DEFAULT_BACKEND = "https://dj-tracks-trovira97.fly.dev"

# Default Ko-fi username — overridden by settings.json["kofi_username"].
DEFAULT_KOFI_USERNAME = "trovira_97"


def usage_call(action: str, device_id: str,
               discord_id: str | None = None,
               timeout: float = 4.0) -> dict | None:
    """POST to /usage/{action} with the device id.

    Returns the server's state dict on success, None on any network
    failure so the caller can fall back to its offline shadow.
    """
    if not device_id:
        return None
    body = {"device_id": device_id}
    if discord_id:
        body["discord_id"] = discord_id
    try:
        import requests
        r = requests.post(
            f"{_backend_url()}/usage/{action}",
            json=body, timeout=timeout,
            headers={"User-Agent": "dj-tracks-app"},
        )
        if r.status_code != 200:
            log.info(f"[Donor] /usage/{action} HTTP {r.status_code}")
            return None
        return r.json()
    except Exception as exc:
        log.info(f"[Donor] /usage/{action} failed: {exc}")
        return None


def kofi_url() -> str:
    """Return the Ko-fi donation URL for this install."""
    try:
        import json

        from utils.paths import config_dir
        p = config_dir() / "settings.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            user = (data.get("kofi_username") or "").strip()
            if user:
                return f"https://ko-fi.com/{user}"
    except Exception:
        pass
    return f"https://ko-fi.com/{DEFAULT_KOFI_USERNAME}"


def _backend_url() -> str:
    env = os.environ.get("DJ_TRACKS_BACKEND")
    if env:
        return env.rstrip("/")
    try:
        import json

        from utils.paths import config_dir
        p = config_dir() / "settings.json"
        if p.exists():
            data = json.loads(p.read_text(encoding="utf-8"))
            url = (data.get("backend_url") or "").strip().rstrip("/")
            if url:
                return url
    except Exception:
        pass
    return DEFAULT_BACKEND


def check_donor(discord_user_id: str, timeout: float = 5.0) -> bool | None:
    """Ask the backend whether *discord_user_id* has the Donor role.

    Returns True / False on a clean response, None on any error.  The
    caller should treat None as "don't change cached state".
    """
    if not discord_user_id:
        return None
    try:
        import requests
        r = requests.get(
            f"{_backend_url()}/verify",
            params={"discord_id": discord_user_id},
            timeout=timeout,
            headers={"User-Agent": "dj-tracks-app"},
        )
        if r.status_code != 200:
            log.info(f"[Donor] backend HTTP {r.status_code}")
            return None
        data = r.json() or {}
        return bool(data.get("donor", False))
    except Exception as exc:
        log.info(f"[Donor] verify failed: {exc}")
        return None


def open_oauth_flow(local_token: str) -> bool:
    """Open the system browser pointing at the backend's OAuth start.

    *local_token* is a one-time random string the app generates and
    later polls for; the backend writes the result of the OAuth flow
    keyed by that token so the app can pick it up without needing a
    callback server of its own.

    Returns True if the browser launch succeeded.
    """
    url = f"{_backend_url()}/discord/start?token={local_token}"
    try:
        return webbrowser.open(url)
    except Exception as exc:
        log.warning(f"[Donor] could not open browser: {exc}")
        return False


def poll_oauth_result(local_token: str, timeout: float = 5.0) -> dict | None:
    """Poll the backend for the result of an in-progress OAuth flow.

    Returns ``{discord_user_id, discord_username, donor}`` once the
    user finishes the flow, or None while still pending.
    """
    if not local_token:
        return None
    try:
        import requests
        r = requests.get(
            f"{_backend_url()}/discord/poll",
            params={"token": local_token},
            timeout=timeout,
            headers={"User-Agent": "dj-tracks-app"},
        )
        if r.status_code == 202:
            return None                # still pending
        if r.status_code != 200:
            return None
        data = r.json() or {}
        if not data.get("discord_user_id"):
            return None
        return data
    except Exception:
        return None
