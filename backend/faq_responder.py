"""
backend/faq_responder.py
=========================
Rule-based FAQ responder for the #ayuda channel.

Given a user question, returns the best-matching canned answer by
counting keyword hits — no LLM, no API cost, deterministic.

Design goals:
- Zero external dependencies.
- Trivial to extend: append to FAQ_ENTRIES.
- Never gives a wrong answer with low confidence — needs at least
  the entry's ``threshold`` keyword matches before returning it.
- Optional per-user rate limiting via helper functions in bot.py.
"""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class FaqEntry:
    """One canned Q&A entry."""
    keywords: tuple[str, ...]
    title:    str
    answer:   str
    threshold: int = 1


# ── FAQ knowledge base ─────────────────────────────────────────────────────
# Add new entries here.  Order matters when two entries tie on score — the
# earlier one wins.  Keep the most specific ones first.

FAQ_ENTRIES: list[FaqEntry] = [
    FaqEntry(
        keywords=("smartscreen", "editor desconocido", "windows protegido",
                  "windows me avisa", "peligroso", "no me deja abrir",
                  "protegio", "protegió"),
        title="SmartScreen te avisa al abrir la app",
        answer=(
            "Es normal — la app no está firmada digitalmente.  Cuando Windows "
            "te muestre el aviso:\n\n"
            "1. Pulsa **\"Más información\"**\n"
            "2. Pulsa **\"Ejecutar de todas formas\"**\n\n"
            "Solo aparece la primera vez que la abres."
        ),
    ),
    FaqEntry(
        keywords=("spotify", "client id", "client secret",
                  "credenciales spotify", "api spotify",
                  "configurar spotify", "no puedo usar spotify"),
        title="Configurar Spotify",
        answer=(
            "Necesitas Client ID + Secret (gratis) de Spotify:\n\n"
            "1. Ve a https://developer.spotify.com/dashboard\n"
            "2. Login con tu cuenta de Spotify\n"
            "3. **Create app** → nombre libre, Redirect URI "
            "`http://localhost:8888/callback`, marca **Web API** → Save\n"
            "4. En Settings, copia **Client ID** + **View client secret**\n"
            "5. Pega ambos en la app: **Ajustes → Credenciales de API**\n\n"
            "Guía completa: https://github.com/trovira97/dj-tracks#-configuración-de-apis"
        ),
    ),
    FaqEntry(
        keywords=("doné", "done", "donación", "donacion", "rol donor",
                  "no me llegó el rol", "no me llego el rol",
                  "no tengo donor", "no tengo el rol",
                  "!donate", "kofi", "ko-fi", "vincular discord"),
        title="Donar y desbloquear la app",
        answer=(
            "**Cómo donar y desbloquear la app**\n\n"
            "1. Escríbeme **`!donate <importe>`** por DM (yo, el bot)\n"
            "2. Te devuelvo un enlace Ko-fi personalizado con tu Discord ID\n"
            "3. Pega tu ID en el mensaje al donar\n"
            "4. En segundos: rol Donor asignado + app desbloqueada\n\n"
            "**Si ya donaste sin pegar el ID:**\n"
            "1. Abre DJ Tracks\n"
            "2. Modal \"Has llegado al límite\" → **\"Ya doné · vincular Discord\"**\n"
            "3. OAuth te detecta por email automáticamente\n\n"
            "**Si perdiste el rol** (saliste y volviste al server): escríbeme "
            "**`!fixrole`** por DM."
        ),
    ),
    FaqEntry(
        keywords=("no abre", "no arranca", "crashea", "crasea",
                  "cierra sola", "se cuelga", "no funciona la app",
                  "no me abre", "no inicia", "no responde"),
        title="La app no arranca o se cierra",
        answer=(
            "**Para diagnosticarlo:**\n\n"
            "1. Abre la app (si abre aunque sea un momento)\n"
            "2. Ve al panel **LOGS** (sidebar izquierda)\n"
            "3. Filtra por **ERROR**\n"
            "4. Pulsa **📋 Copiar todo**\n"
            "5. Pega el error en <#🐛-bugs> con tu OS y versión\n\n"
            "**Si ni se abre**: navega a `%APPDATA%\\DJ Tracks\\logs\\` y copia el "
            "log más reciente."
        ),
    ),
    FaqEntry(
        keywords=("beatport", "sin bpm", "sin key", "camelot", "sin metadata",
                  "no salen bpm", "no hay bpm", "faltan datos", "sin género"),
        title="No sale BPM / key / Camelot",
        answer=(
            "Beatport es scraping del catálogo público.  Si no aparece la "
            "metadata:\n\n"
            "- El track no está en Beatport (común en pop / rock; muy fiable "
            "en electrónica)\n"
            "- Activa el fallback GetSongBPM: **Ajustes → Análisis DJ → API Key**\n"
            "- Como último recurso, `librosa` analiza el archivo local "
            "(desactivado por default, actívalo en Ajustes)\n\n"
            "El **badge** en el historial (BEATPORT / DB / LOCAL) te dice "
            "de dónde vino la data."
        ),
    ),
    FaqEntry(
        keywords=("mac", "macos", "linux", "ubuntu", "apple silicon", "m1", "m2"),
        title="¿Funciona en Mac / Linux?",
        answer=(
            "Actualmente **solo Windows** (compilado con PyInstaller para .exe).\n\n"
            "El código Python es cross-platform, así que teóricamente sí, "
            "pero no está empaquetado.  Si sabes Python:\n\n"
            "```bash\n"
            "git clone https://github.com/trovira97/dj-tracks\n"
            "cd dj-tracks\n"
            "pip install -r requirements.txt\n"
            "python main.py\n"
            "```\n\n"
            "Funcionará con algunas limitaciones (no drag-and-drop, "
            "notificaciones nativas variables por OS).\n\n"
            "Build oficial para Mac / Linux está en el roadmap."
        ),
    ),
    FaqEntry(
        keywords=("actualización", "actualizacion", "actualizar", "actualizo",
                  "actualiza", "update", "nueva versión", "auto-update",
                  "auto update", "no me deja actualizar"),
        title="Actualizar DJ Tracks",
        answer=(
            "**Auto-update**: al arrancar, la app comprueba GitHub → si hay "
            "versión nueva sale un toast.  **Ajustes → \"Buscar actualizaciones\"** "
            "→ confirma → se instala solo.\n\n"
            "**Si falla el auto-update:**\n"
            "- Descarga manual: https://github.com/trovira97/dj-tracks/releases/latest\n"
            "- Extrae el zip encima de tu carpeta de instalación actual"
        ),
    ),
    FaqEntry(
        keywords=("403", "forbidden", "youtube 403", "not available",
                  "no descarga youtube", "acceso denegado"),
        title="Error 403 / \"Forbidden\" en YouTube",
        answer=(
            "Casi siempre es yt-dlp obsoleto — YouTube cambia sus "
            "signature algorithms cada 2-3 meses.\n\n"
            "**Fix rápido:**\n"
            "1. **Ajustes → Mantenimiento → Actualizar yt-dlp**\n"
            "2. Reinicia la app\n"
            "3. Vuelve a intentar la descarga\n\n"
            "Si el 403 es específico a un track: prueba el **retry "
            "cross-platform** (activo por default)."
        ),
    ),
    FaqEntry(
        keywords=("drm", "protegido", "geo", "restricción", "restriccion",
                  "no me deja descargar", "bloqueado", "region",
                  "not available in your country"),
        title="Track bloqueado por DRM / región",
        answer=(
            "La app tiene **retry cross-platform automático** — cuando un track "
            "falla en una plataforma, busca en las otras.\n\n"
            "Verifica que está activado: **Ajustes → Reintento cross-platform** "
            "(default ON).\n\n"
            "**Para contenido login-only en SoundCloud/YouTube:**\n"
            "**Ajustes → Cookies del navegador** → selecciona tu navegador.\n"
            "La app usará tu sesión legítima para descargar."
        ),
    ),
    FaqEntry(
        keywords=("instalar", "instalo", "instala", "como empiezo",
                  "cómo empiezo", "primera vez", "descargar app",
                  "cómo funciona", "como funciona", "instalación", "instalacion"),
        title="Cómo instalar DJ Tracks",
        answer=(
            "**Instalación en 4 pasos:**\n\n"
            "1. Descarga el zip: https://github.com/trovira97/dj-tracks/releases/latest\n"
            "2. Extrae en una carpeta (ej. `C:\\Programs\\DJ Tracks`)\n"
            "3. Doble-click en **`DJ Tracks.exe`**\n"
            "4. La primera vez SmartScreen avisará — mira arriba para eso\n\n"
            "Si vas a usar Spotify, también necesitas configurar credenciales "
            "(gratis).  Pregunta \"cómo configurar Spotify\" y te paso los pasos."
        ),
    ),
    FaqEntry(
        keywords=("discord id", "user id", "como saco mi id", "cómo saco mi id",
                  "no sé mi id", "no se mi id", "developer mode", "modo desarrollador"),
        title="Sacar tu Discord User ID",
        answer=(
            "**La forma más rápida:**\n"
            "Escríbeme **`!donate <€>`** por DM — te devuelvo un embed con "
            "tu ID en un bloque de código listo para copiar.\n\n"
            "**Manual:**\n"
            "1. Discord → **Ajustes de usuario → Avanzado → Modo desarrollador ON**\n"
            "2. Click derecho en tu propio nombre → **Copiar ID de usuario**"
        ),
    ),
]


# ── Matching ───────────────────────────────────────────────────────────────

_MIN_LEN = 8    # ignore very short "hi" / "help?" style messages


def _normalise(text: str) -> str:
    """Lowercase + strip accents for lenient matching."""
    text = text.lower()
    # Simple ASCII-fold for common accents.
    accents = {"á": "a", "é": "e", "í": "i", "ó": "o", "ú": "u", "ñ": "n"}
    for src, dst in accents.items():
        text = text.replace(src, dst)
    # Collapse whitespace.
    text = re.sub(r"\s+", " ", text)
    return text


def match(text: str) -> FaqEntry | None:
    """Return the best-scoring FAQ entry for *text*, or None."""
    if not text or len(text.strip()) < _MIN_LEN:
        return None
    norm = _normalise(text)
    best_score = 0
    best_entry: FaqEntry | None = None
    for entry in FAQ_ENTRIES:
        # Count unique keyword matches.  Substring match is intentional —
        # user's phrase can embed the keyword anywhere.
        matched = sum(1 for kw in entry.keywords if _normalise(kw) in norm)
        if matched >= entry.threshold and matched > best_score:
            best_score = matched
            best_entry = entry
    return best_entry
