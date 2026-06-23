"""
ui/setup_wizard.py
==================
Step-by-step "How to set up Spotify credentials" modal.

Spotify metadata search needs a free Developer app (Client ID + Secret).
This dialog walks the user through creating one and pasting the keys into
Settings — modelled on the donations modal so it matches every theme.
"""
from __future__ import annotations

import webbrowser
from typing import Callable, Dict, Optional

import customtkinter as ctk

_DASHBOARD = "https://developer.spotify.com/dashboard"


def show_setup_wizard(root, palette: Dict[str, str],
                      on_open_settings: Optional[Callable] = None) -> None:
    """
    Open the setup wizard on top of *root* using the active *palette*.

    Args:
        root:             Parent ``ctk.CTk`` window.
        palette:          Active theme palette (the global ``C`` dict).
        on_open_settings: Optional callback to jump to the Settings tab.
    """
    C = palette

    win = ctk.CTkToplevel(root)
    win.title("Cómo configurar Spotify")
    win.configure(fg_color=C["bg"])
    win.transient(root)
    win.grab_set()

    ctk.CTkFrame(win, height=3, fg_color=C["spotify"], corner_radius=0).pack(fill="x")

    # Header.
    hdr = ctk.CTkFrame(win, fg_color=C["panel"], corner_radius=0)
    hdr.pack(fill="x")
    ctk.CTkLabel(hdr, text="🔑  Configurar credenciales de Spotify",
                 font=ctk.CTkFont(size=15, weight="bold"),
                 text_color=C["spotify"]).pack(padx=20, pady=12, anchor="w")

    body = ctk.CTkScrollableFrame(win, fg_color="transparent",
                                  scrollbar_button_color=C["border"])
    body.pack(fill="both", expand=True, padx=18, pady=(8, 4))

    def _section(title: str, color: Optional[str] = None) -> None:
        ctk.CTkLabel(body, text=title, font=ctk.CTkFont(size=11, weight="bold"),
                     text_color=color or C["accent"], anchor="w").pack(
                         fill="x", pady=(12, 4))

    def _step(text: str) -> None:
        ctk.CTkLabel(body, text=text, font=ctk.CTkFont(size=11),
                     text_color=C["text_mid"], anchor="w", justify="left",
                     wraplength=440).pack(fill="x", padx=(6, 0), pady=1)

    ctk.CTkLabel(
        body,
        text="Spotify no permite descargar audio, pero sus credenciales "
             "gratuitas dan los mejores metadatos (nombre, álbum, año, "
             "carátula).  Apple Music · SoundCloud · Bandcamp funcionan sin "
             "configurar nada.",
        font=ctk.CTkFont(size=10), text_color=C["text_dim"],
        wraplength=450, justify="left").pack(fill="x", pady=(4, 2))

    # Step 1
    _section("Paso 1 — Crea una app de desarrollador (gratis)")
    _step("1.  Abre el panel de desarrollador de Spotify (botón de abajo).")
    _step("2.  Inicia sesión con tu cuenta normal (no hace falta Premium).")
    _step('3.  Pulsa «Create app».')
    _step('4.  Pon cualquier nombre y descripción (ej. «DJ Tracks»).')
    _step('5.  En «Redirect URI» escribe:  http://localhost:8888/callback')
    _step('6.  Marca «Web API», acepta los términos y pulsa «Save».')

    # Step 2
    _section("Paso 2 — Copia tus credenciales")
    _step('1.  Dentro de tu app, pulsa «Settings».')
    _step("2.  Copia el  Client ID.")
    _step('3.  Pulsa «View client secret» y cópialo también.')
    _step("4.  Pégalos en  Ajustes → Credenciales de API  de esta app.")
    _step("5.  Pulsa «Guardar configuración». La barra de estado pasará a verde.")

    # Tip
    _section("⚠  Consejo de seguridad", color=C["warning"])
    ctk.CTkLabel(
        body,
        text="Te recomendamos crear una cuenta secundaria GRATIS sólo para "
             "esto — no tu cuenta principal — por si la API marca la app "
             "por uso inusual.",
        font=ctk.CTkFont(size=10, weight="bold"), text_color=C["text"],
        fg_color=C["card"], corner_radius=8, wraplength=440,
        justify="left").pack(fill="x", pady=(2, 6), ipadx=10, ipady=8)

    # Buttons.
    btns = ctk.CTkFrame(win, fg_color="transparent")
    btns.pack(fill="x", padx=18, pady=(4, 14))

    ctk.CTkButton(
        btns, text="🌐  Abrir el panel de Spotify",
        height=38, font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=C["spotify"], hover_color=C["spotify"], text_color="#FFF",
        corner_radius=8, command=lambda: _open(_DASHBOARD)).pack(
            side="left", fill="x", expand=True, padx=(0, 6))

    def _go_settings() -> None:
        win.destroy()
        if on_open_settings:
            on_open_settings()

    ctk.CTkButton(
        btns, text="Ir a Ajustes  →", height=38,
        font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=C["accent"], hover_color=C["accent_dim"], text_color="#000",
        corner_radius=8, command=_go_settings).pack(
            side="left", fill="x", expand=True, padx=(6, 0))

    ctk.CTkButton(
        win, text="Cerrar", width=120, height=30,
        font=ctk.CTkFont(size=10), fg_color=C["surface"],
        hover_color=C["card_hover"], text_color=C["text_mid"],
        corner_radius=6, command=win.destroy).pack(pady=(0, 14))

    # Size + centre over parent.
    win.update_idletasks()
    ww, wh = 500, 620
    rx, ry = root.winfo_x(), root.winfo_y()
    rw, rh = root.winfo_width(), root.winfo_height()
    win.geometry(f"{ww}x{wh}+{rx + (rw - ww)//2}+{ry + (rh - wh)//2}")


def _open(url: str) -> None:
    try:
        webbrowser.open(url, new=2)
    except Exception:
        pass
