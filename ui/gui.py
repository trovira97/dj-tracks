"""
ui/gui.py  —  DJ Tracks Music Downloader
=========================================
Interfaz profesional estilo software DJ (Rekordbox / Serato / Traktor).
4 temas visuales · Dashboard · Historial · Búsqueda con filtros.

Python 3.10+  ·  CustomTkinter  ·  Pillow
"""
from __future__ import annotations

import io
import os
import platform
import subprocess
import threading
import webbrowser
from collections import OrderedDict
from pathlib import Path
from tkinter import PhotoImage, filedialog
from typing import Callable, Dict, List, Optional, Tuple
import tkinter as tk

import customtkinter as ctk
from PIL import Image
import requests

from __version__ import __app_name__, __app_subtitle__, __version__
from core.controller import AppController
from downloader.audio_downloader import DownloadStatus, DownloadTask
from providers import TrackInfo
from utils.history_manager import HistoryManager
from utils.paths import bundled_resource


# ─────────────────────────────────────────────────────────────────────────────
# Platform-aware helpers
# ─────────────────────────────────────────────────────────────────────────────

def _open_in_file_manager(path: Path) -> None:
    """Reveal *path* in the system file manager (Explorer / Finder / xdg-open)."""
    try:
        p = path if path.exists() else path.parent
        if not p.exists():
            return
        system = platform.system()
        if system == "Windows":
            if p.is_dir():
                os.startfile(str(p))                          # noqa: S606
            else:
                subprocess.Popen(["explorer", "/select,", str(p)])
        elif system == "Darwin":
            subprocess.Popen(["open", "-R", str(p)] if p.is_file() else ["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p if p.is_dir() else p.parent)])
    except Exception:
        pass


def _open_url(url: str) -> None:
    """Open *url* in the user's default browser."""
    if url:
        try:
            webbrowser.open(url, new=2)
        except Exception:
            pass


def _copy_to_clipboard(root: ctk.CTk, text: str) -> None:
    """Copy *text* to the system clipboard."""
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
    except Exception:
        pass

# ─────────────────────────────────────────────────────────────────────────────
# Theme system
# ─────────────────────────────────────────────────────────────────────────────

THEMES: Dict[str, Dict[str, str]] = {
    "Dark Pro": {
        "bg": "#08080F", "sidebar": "#0B0B17", "panel": "#0F0F1D",
        "card": "#141426", "card_hover": "#1C1C38", "surface": "#17172C",
        "border": "#252540", "border_focus": "#2C2C52",
        "accent": "#00C8FF", "accent_dim": "#0088AA", "accent2": "#7C3AED",
        "text": "#DCE0F5", "text_mid": "#8088AA", "text_dim": "#505070",
        "success": "#00D48A", "error": "#FF4466", "warning": "#FFB020",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500",
        "done_tint": "#0D1F18", "error_tint": "#1F0D12",
    },
    "Neon Blue": {
        "bg": "#020208", "sidebar": "#040412", "panel": "#060618",
        "card": "#0A0A20", "card_hover": "#10103A", "surface": "#080820",
        "border": "#0F1045", "border_focus": "#1530B0",
        "accent": "#1E90FF", "accent_dim": "#0055CC", "accent2": "#00DDCC",
        "text": "#D0E8FF", "text_mid": "#5878AA", "text_dim": "#2C4060",
        "success": "#00FF99", "error": "#FF3366", "warning": "#FFCC00",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500",
        "done_tint": "#0A2018", "error_tint": "#200810",
    },
    "Neon Purple": {
        "bg": "#06020C", "sidebar": "#0A0418", "panel": "#0C0620",
        "card": "#130828", "card_hover": "#1C1038", "surface": "#10061C",
        "border": "#220838", "border_focus": "#5515A8",
        "accent": "#A020FF", "accent_dim": "#6010CC", "accent2": "#FF20AA",
        "text": "#EED0FF", "text_mid": "#7848AA", "text_dim": "#4C2C66",
        "success": "#20FF80", "error": "#FF2050", "warning": "#FFAA20",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500",
        "done_tint": "#0A1C12", "error_tint": "#1C060C",
    },
    "Carbon Black": {
        "bg": "#080808", "sidebar": "#0E0E0E", "panel": "#121212",
        "card": "#1A1A1A", "card_hover": "#222222", "surface": "#161616",
        "border": "#2A2A2A", "border_focus": "#444444",
        "accent": "#FF6B00", "accent_dim": "#CC5500", "accent2": "#FFB800",
        "text": "#F0EEE8", "text_mid": "#888880", "text_dim": "#505048",
        "success": "#00CC66", "error": "#FF3333", "warning": "#FFCC00",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500",
        "done_tint": "#0C1A10", "error_tint": "#1A0808",
    },
}

# Active theme palette — updated by apply_theme().
C: Dict[str, str] = dict(THEMES["Dark Pro"])

PLATFORM_COLORS: Dict[str, str] = {}
PLATFORM_LABELS: Dict[str, str] = {
    "spotify": "SPOTIFY", "applemusic": "APPLE MUSIC", "soundcloud": "SOUNDCLOUD",
}


def apply_theme(name: str) -> None:
    """Update the global C palette and platform colour refs from a named theme."""
    global C, PLATFORM_COLORS
    t = THEMES.get(name, THEMES["Dark Pro"])
    C.update(t)
    PLATFORM_COLORS.update({
        "spotify": C["spotify"], "applemusic": C["apple"], "soundcloud": C["sc"],
    })


apply_theme("Dark Pro")

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


def _font(size: int = 12, weight: str = "normal", mono: bool = False) -> ctk.CTkFont:
    """Return a CTkFont with the given attributes."""
    kw: dict = {"size": size, "weight": weight}
    if mono:
        kw["family"] = "Consolas"
    return ctk.CTkFont(**kw)


# ─────────────────────────────────────────────────────────────────────────────
# Cover art — LRU-cached, async
# ─────────────────────────────────────────────────────────────────────────────

class _LRUImageCache:
    """Thread-safe LRU cache for CTkImage objects, capped at *maxsize* entries."""

    def __init__(self, maxsize: int = 300) -> None:
        self._cache: OrderedDict[Tuple[str, int], ctk.CTkImage] = OrderedDict()
        self._maxsize = maxsize
        self._lock    = threading.Lock()

    def get(self, key: Tuple[str, int]) -> Optional[ctk.CTkImage]:
        with self._lock:
            if key in self._cache:
                self._cache.move_to_end(key)
                return self._cache[key]
        return None

    def put(self, key: Tuple[str, int], value: ctk.CTkImage) -> None:
        with self._lock:
            self._cache[key] = value
            self._cache.move_to_end(key)
            while len(self._cache) > self._maxsize:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()

    def size(self) -> int:
        """Number of cached images currently held."""
        with self._lock:
            return len(self._cache)


_COVER_CACHE = _LRUImageCache(maxsize=300)


def _placeholder(size: int) -> ctk.CTkImage:
    img = Image.new("RGB", (size, size), C["border"])
    try:
        from PIL import ImageDraw
        draw = ImageDraw.Draw(img)
        fs = max(10, size // 3)
        draw.text((size // 2 - fs // 3, size // 2 - fs // 2), "♪", fill=C["text_dim"])
    except Exception:
        pass
    return ctk.CTkImage(light_image=img, dark_image=img, size=(size, size))


def _load_cover_async(root_widget, label: ctk.CTkLabel, url: str, size: int = 56) -> None:
    """Set a placeholder immediately, then fetch and display the real cover art."""
    ph = _placeholder(size)
    label.configure(image=ph, text="")
    label._img_ref = ph
    if not url:
        return

    key = (url, size)
    cached = _COVER_CACHE.get(key)
    if cached:
        label.configure(image=cached)
        label._img_ref = cached
        return

    def _fetch() -> None:
        try:
            resp = requests.get(url, timeout=8)
            resp.raise_for_status()
            ct = resp.headers.get("Content-Type", "")
            if ct and "image" not in ct:
                return
            pil = Image.open(io.BytesIO(resp.content)).convert("RGB")
            pil = pil.resize((size, size), Image.Resampling.LANCZOS)
            img = ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
            _COVER_CACHE.put(key, img)
            root_widget.after(0, lambda: (
                label.configure(image=img), setattr(label, "_img_ref", img)))
        except Exception:
            pass

    threading.Thread(target=_fetch, daemon=True).start()


# ─────────────────────────────────────────────────────────────────────────────
# Base components
# ─────────────────────────────────────────────────────────────────────────────

class Divider(ctk.CTkFrame):
    def __init__(self, parent, **kw):
        super().__init__(parent, height=1, fg_color=C["border"], **kw)


class SectionLabel(ctk.CTkLabel):
    def __init__(self, parent, text: str, **kw):
        super().__init__(parent, text=text.upper(), text_color=C["text_dim"],
                         font=_font(9, "bold"), **kw)


class StatusBadge(ctk.CTkLabel):
    _BG  = {
        DownloadStatus.PENDING:     "#1A1A35",
        DownloadStatus.SEARCHING:   "#7C3AED",
        DownloadStatus.DOWNLOADING: "#00C8FF",
        DownloadStatus.PROCESSING:  "#FFB020",
        DownloadStatus.DONE:        "#00D48A",
        DownloadStatus.ERROR:       "#FF4466",
        DownloadStatus.CANCELLED:   "#1A1A35",
    }
    _FG  = {
        DownloadStatus.PENDING:     "#8088AA",
        DownloadStatus.SEARCHING:   "#FFF",
        DownloadStatus.DOWNLOADING: "#000",
        DownloadStatus.PROCESSING:  "#000",
        DownloadStatus.DONE:        "#000",
        DownloadStatus.ERROR:       "#FFF",
        DownloadStatus.CANCELLED:   "#404060",
    }
    _TXT = {
        DownloadStatus.PENDING:     "· en cola",
        DownloadStatus.SEARCHING:   "⌕ buscando",
        DownloadStatus.DOWNLOADING: "↓ descargando",
        DownloadStatus.PROCESSING:  "◈ procesando",
        DownloadStatus.DONE:        "✓ listo",
        DownloadStatus.ERROR:       "✕ error",
        DownloadStatus.CANCELLED:   "− cancelado",
    }

    def __init__(self, parent, status: DownloadStatus = DownloadStatus.PENDING, **kw):
        super().__init__(parent, text=self._TXT[status], fg_color=self._BG[status],
                         text_color=self._FG[status], corner_radius=4,
                         font=_font(9), width=98, height=18, **kw)

    def set_status(self, s: DownloadStatus) -> None:
        self.configure(text=self._TXT[s], fg_color=self._BG[s], text_color=self._FG[s])


class Toast(ctk.CTkFrame):
    _COLORS = {"info": None, "success": "#00D48A", "error": "#FF4466"}

    def __init__(self, root: ctk.CTk, message: str, kind: str = "info", ms: int = 2800):
        color = self._COLORS.get(kind) or C["accent"]
        super().__init__(root, fg_color="#16162A", corner_radius=8,
                         border_width=1, border_color=color)
        ctk.CTkLabel(self, text=message, text_color=C["text"], font=_font(12),
                     wraplength=320, justify="left").pack(padx=16, pady=10)
        ctk.CTkFrame(self, width=3, fg_color=color, corner_radius=0).place(x=0, y=0, relheight=1)

        root.update_idletasks()
        rw, rh = root.winfo_width(), root.winfo_height()
        w, h   = 360, 56
        x      = max(0, rw - w - 16)
        y      = max(0, rh - h - 16)
        self.place(x=x, y=y, width=w, height=h)
        root.after(ms, self._safe_destroy)

    def _safe_destroy(self) -> None:
        try:
            self.destroy()
        except Exception:
            pass


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard widgets
# ─────────────────────────────────────────────────────────────────────────────

class StatCard(ctk.CTkFrame):
    """Metric card: coloured left stripe + big number + label."""

    def __init__(self, parent, value: str, label: str, color: Optional[str] = None, **kw):
        color = color or C["accent"]
        super().__init__(parent, fg_color=C["card"], corner_radius=8, **kw)

        ctk.CTkFrame(self, width=3, fg_color=color, corner_radius=0).pack(
            side="left", fill="y")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(14, 14), pady=14)

        self._value_lbl = ctk.CTkLabel(body, text=value, font=_font(26, "bold"),
                                       text_color=color, anchor="w")
        self._value_lbl.pack(fill="x")
        ctk.CTkLabel(body, text=label, font=_font(9), text_color=C["text_dim"],
                     anchor="w").pack(fill="x")

    def update_value(self, value: str, color: Optional[str] = None) -> None:
        kw: dict = {"text": value}
        if color:
            kw["text_color"] = color
        self._value_lbl.configure(**kw)


class MiniWaveform(tk.Canvas):
    """Decorative waveform bar chart (visual only, no audio analysis)."""

    def __init__(self, parent, width: int = 60, height: int = 20, **kw):
        import random
        super().__init__(parent, width=width, height=height,
                         bg=C["card"], highlightthickness=0, **kw)
        bar_w  = 3
        gap    = 1
        n_bars = width // (bar_w + gap)
        color  = C["accent"]
        for i in range(n_bars):
            h = random.randint(3, height - 2)
            x0 = i * (bar_w + gap)
            x1 = x0 + bar_w
            y0 = (height - h) // 2
            y1 = y0 + h
            self.create_rectangle(x0, y0, x1, y1, fill=color, outline="")


# ─────────────────────────────────────────────────────────────────────────────
# Search result widgets
# ─────────────────────────────────────────────────────────────────────────────

class _TrackContextMenuMixin:
    """Adds a right-click context menu with platform-aware actions."""

    def _show_track_menu(self, event, track: TrackInfo) -> None:
        menu = tk.Menu(self, tearoff=0,
                       bg=C["card"], fg=C["text"],
                       activebackground=C["accent"], activeforeground="#000",
                       borderwidth=0)
        plat_label = PLATFORM_LABELS.get(track.platform, "plataforma").title()
        menu.add_command(label=f"Abrir en {plat_label}",
                         command=lambda: _open_url(track.source_url),
                         state="normal" if track.source_url else "disabled")
        menu.add_command(label="Copiar enlace",
                         command=lambda: _copy_to_clipboard(self.winfo_toplevel(), track.source_url),
                         state="normal" if track.source_url else "disabled")
        menu.add_separator()
        menu.add_command(label="Copiar título",
                         command=lambda: _copy_to_clipboard(
                             self.winfo_toplevel(),
                             f"{track.artist_str} — {track.title}"))
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


class TrackRow(ctk.CTkFrame, _TrackContextMenuMixin):
    """Horizontal list row for search results."""

    def __init__(self, parent, track: TrackInfo, on_add: Callable, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=6, **kw)
        self._track  = track
        self._on_add = on_add
        self._added  = False
        self._build()
        self.bind("<Enter>", lambda _: self.configure(fg_color=C["card_hover"]) if not self._added else None)
        self.bind("<Leave>", lambda _: self.configure(fg_color=C["card"])       if not self._added else None)
        self.bind("<Button-3>", lambda e, t=track: self._show_track_menu(e, t))

    def _build(self) -> None:
        t  = self._track
        pc = PLATFORM_COLORS.get(t.platform, C["text_dim"])

        ctk.CTkFrame(self, width=3, fg_color=pc, corner_radius=0).pack(side="left", fill="y")

        self._cover = ctk.CTkLabel(self, text="", width=56, height=56)
        self._cover.pack(side="left", padx=(10, 12), pady=10)
        _load_cover_async(self, self._cover, t.cover_url, 56)

        right = ctk.CTkFrame(self, fg_color="transparent", width=120)
        right.pack(side="right", fill="y", padx=12)
        right.pack_propagate(False)

        ctk.CTkLabel(right, text=PLATFORM_LABELS.get(t.platform, ""),
                     font=_font(8, "bold"), text_color=pc).pack(anchor="e", pady=(12, 4))
        self._btn = ctk.CTkButton(right, text="＋", width=36, height=36,
                                   font=_font(15, "bold"), fg_color=C["accent"],
                                   hover_color=C["accent_dim"], text_color="#000",
                                   corner_radius=6, command=self._add)
        self._btn.pack(anchor="e")

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=10)

        top = ctk.CTkFrame(info, fg_color="transparent")
        top.pack(fill="x")
        ctk.CTkLabel(top, text=t.title or "Unknown", font=_font(13, "bold"),
                     text_color=C["text"], anchor="w").pack(side="left")
        if t.year:
            ctk.CTkLabel(top, text=f"  {t.year}", font=_font(10),
                         text_color=C["text_dim"]).pack(side="left")

        ctk.CTkLabel(info, text=t.artist_str or "Unknown", font=_font(11),
                     text_color=C["text_mid"], anchor="w").pack(fill="x")

        bot = ctk.CTkFrame(info, fg_color="transparent")
        bot.pack(fill="x", pady=(3, 0))
        if t.album:
            ctk.CTkLabel(bot, text=t.album, font=_font(10),
                         text_color=C["text_dim"], anchor="w").pack(side="left")
        ctk.CTkLabel(bot, text=t.duration_str, font=_font(10, mono=True),
                     text_color=C["text_dim"]).pack(side="right")

    def _add(self) -> None:
        if self._added:
            return
        self._added = True
        self._btn.configure(text="✓", fg_color=C["success"], state="disabled")
        self._on_add(self._track)

    def flash(self) -> None:
        self.configure(fg_color=C["card_hover"])
        self.after(200, lambda: self.configure(fg_color=C["card"]))


class TrackCard(ctk.CTkFrame, _TrackContextMenuMixin):
    """Grid card for search results."""

    _CARD_W = 185
    _CARD_H = 275

    def __init__(self, parent, track: TrackInfo, on_add: Callable, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=8,
                         width=self._CARD_W, height=self._CARD_H, **kw)
        self.grid_propagate(False)
        self._track  = track
        self._on_add = on_add
        self._added  = False
        self._build()
        self.bind("<Button-3>", lambda e, t=track: self._show_track_menu(e, t))

    def _build(self) -> None:
        t  = self._track
        pc = PLATFORM_COLORS.get(t.platform, C["text_dim"])

        ctk.CTkFrame(self, height=3, fg_color=pc, corner_radius=0).pack(fill="x")

        self._cover = ctk.CTkLabel(self, text="", width=155, height=155)
        self._cover.pack(padx=15, pady=(10, 6))
        _load_cover_async(self, self._cover, t.cover_url, 155)

        ctk.CTkLabel(self, text=t.title or "Unknown", font=_font(12, "bold"),
                     text_color=C["text"], anchor="w", wraplength=161,
                     justify="left").pack(fill="x", padx=12)

        sub = f"{t.artist_str or '—'}" + (f"  ·  {t.year}" if t.year else "")
        ctk.CTkLabel(self, text=sub, font=_font(10), text_color=C["text_mid"],
                     anchor="w", wraplength=161,
                     justify="left").pack(fill="x", padx=12, pady=(2, 0))

        bot = ctk.CTkFrame(self, fg_color="transparent")
        bot.pack(side="bottom", fill="x", padx=12, pady=10)
        ctk.CTkLabel(bot, text=PLATFORM_LABELS.get(t.platform, "")[:2],
                     font=_font(8, "bold"), text_color=pc).pack(side="left")
        self._btn = ctk.CTkButton(bot, text="＋", width=34, height=30,
                                   font=_font(14, "bold"), fg_color=C["accent"],
                                   hover_color=C["accent_dim"], text_color="#000",
                                   corner_radius=5, command=self._add)
        self._btn.pack(side="right")
        ctk.CTkLabel(bot, text=t.duration_str, font=_font(9, mono=True),
                     text_color=C["text_dim"]).pack(side="right", padx=(0, 6))

    def _add(self) -> None:
        if self._added:
            return
        self._added = True
        self._btn.configure(text="✓", fg_color=C["success"], state="disabled")
        self._on_add(self._track)

    def flash(self) -> None:
        self.configure(fg_color=C["card_hover"])
        self.after(200, lambda: self.configure(fg_color=C["card"]))


# ─────────────────────────────────────────────────────────────────────────────
# Download queue row
# ─────────────────────────────────────────────────────────────────────────────

class QueueRow(ctk.CTkFrame):
    _PBAR = {DownloadStatus.DONE: "#00D48A", DownloadStatus.ERROR: "#FF4466",
             DownloadStatus.CANCELLED: "#404060"}

    def __init__(self, parent, task: DownloadTask, on_remove: Callable, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=6, **kw)
        self._task     = task
        self._on_remove = on_remove
        self._pbar: Optional[ctk.CTkProgressBar] = None
        self._badge: Optional[StatusBadge] = None
        self._path_lbl: Optional[ctk.CTkLabel] = None
        self._err_lbl: Optional[ctk.CTkLabel] = None
        self._build()

    def _build(self) -> None:
        t  = self._task
        pc = PLATFORM_COLORS.get(t.track.platform, C["text_dim"])

        ctk.CTkFrame(self, width=3, fg_color=pc, corner_radius=0).pack(side="left", fill="y")

        # Remove / cancel button — always clickable.
        ctk.CTkButton(self, text="✕", width=30, height=30, font=_font(10),
                      fg_color="transparent", hover_color=C["surface"],
                      text_color=C["text_dim"], corner_radius=5,
                      command=lambda: self._on_remove(self._task)).pack(side="right", padx=10)

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(side="left", fill="both", expand=True, padx=(10, 0), pady=9)

        title_row = ctk.CTkFrame(body, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(title_row, text=t.track.title or "Unknown",
                     font=_font(12, "bold"), text_color=C["text"], anchor="w").pack(side="left")
        self._badge = StatusBadge(title_row, t.status)
        self._badge.pack(side="right", padx=(4, 0))

        ctk.CTkLabel(body, text=t.track.artist_str or "—",
                     font=_font(10), text_color=C["text_mid"], anchor="w").pack(fill="x")

        self._pbar = ctk.CTkProgressBar(body, height=3, fg_color=C["border"],
                                        progress_color=C["accent"], corner_radius=2)
        self._pbar.set(t.progress / 100)
        self._pbar.pack(fill="x", pady=(6, 2))

        meta = ctk.CTkFrame(body, fg_color="transparent")
        meta.pack(fill="x")
        ctk.CTkLabel(meta,
                     text=f"{t.profile.label}  ·  {PLATFORM_LABELS.get(t.track.platform, '')}",
                     font=_font(9), text_color=C["text_dim"]).pack(side="left")

        self._path_lbl = ctk.CTkLabel(body, text="", font=_font(8, mono=True),
                                      text_color=C["text_dim"], anchor="w", wraplength=420)
        self._err_lbl  = ctk.CTkLabel(body, text="", font=_font(9),
                                      text_color=C["error"], anchor="w", wraplength=420)

        # Double-click anywhere on the row opens the file (when DONE).
        self.bind("<Double-Button-1>", self._open_output)
        body.bind("<Double-Button-1>", self._open_output)

    def _open_output(self, _event=None) -> None:
        if self._task.status == DownloadStatus.DONE and self._task.output_path:
            _open_in_file_manager(self._task.output_path)

    def update_task(self, task: DownloadTask) -> None:
        self._task = task
        if self._pbar:
            self._pbar.set(task.progress / 100)
            self._pbar.configure(
                progress_color=self._PBAR.get(task.status, C["accent"]))
        if self._badge:
            self._badge.set_status(task.status)

        if task.status == DownloadStatus.DONE:
            self.configure(fg_color=C["done_tint"])
            if task.output_path and self._path_lbl:
                self._path_lbl.configure(text=f"↳ {task.output_path.name}")
                self._path_lbl.pack(fill="x")
        elif task.status == DownloadStatus.ERROR:
            self.configure(fg_color=C["error_tint"])
            if task.error_msg and self._err_lbl:
                self._err_lbl.configure(text=f"↳ {task.error_msg[:90]}")
                self._err_lbl.pack(fill="x")


# ─────────────────────────────────────────────────────────────────────────────
# History row
# ─────────────────────────────────────────────────────────────────────────────

class HistoryRow(ctk.CTkFrame):
    """One row in the history panel table.

    - Double-click → opens the file in the system file manager.
    - Right-click  → context menu (open file, open folder, copy path).
    - ✕ button     → removes this record from the history.
    """

    def __init__(self, parent, record, on_delete: Optional[Callable] = None, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=5, **kw)
        self._record    = record
        self._on_delete = on_delete
        r  = record
        ok = r.status == "done"
        pc = PLATFORM_COLORS.get(r.platform, C["text_dim"])

        ctk.CTkFrame(self, width=3, fg_color=C["success"] if ok else C["error"],
                     corner_radius=0).pack(side="left", fill="y")
        ctk.CTkLabel(self, text="✓" if ok else "✕",
                     font=_font(11, "bold"),
                     text_color=C["success"] if ok else C["error"],
                     width=24).pack(side="left", padx=(8, 4))

        info = ctk.CTkFrame(self, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, pady=8)
        ctk.CTkLabel(info, text=r.title or "Unknown", font=_font(11, "bold"),
                     text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(info, text=r.artist or "—", font=_font(10),
                     text_color=C["text_mid"], anchor="w").pack(fill="x")

        # Delete button (right-most column).
        self._del_btn = ctk.CTkButton(
            self, text="✕", width=28, height=28, font=_font(11, "bold"),
            fg_color="transparent", hover_color=C["error_tint"],
            text_color=C["text_dim"], corner_radius=5,
            command=self._handle_delete,
        )
        self._del_btn.pack(side="right", padx=(0, 8))

        meta = ctk.CTkFrame(self, fg_color="transparent", width=200)
        meta.pack(side="right", fill="y", padx=(0, 4))
        meta.pack_propagate(False)
        ctk.CTkLabel(meta, text=PLATFORM_LABELS.get(r.platform, r.platform.upper()),
                     font=_font(8, "bold"), text_color=pc, anchor="e").pack(anchor="e", pady=(8, 2))
        ctk.CTkLabel(meta, text=r.quality or "—",
                     font=_font(9), text_color=C["text_dim"], anchor="e").pack(anchor="e")
        ctk.CTkLabel(meta, text=r.date_str,
                     font=_font(8, mono=True), text_color=C["text_dim"], anchor="e").pack(anchor="e")

        # Bind interactions on every child so clicks anywhere on the row work,
        # but skip the delete button (it has its own action).
        self._bind_recursive(self, "<Double-Button-1>", self._open_file, skip=self._del_btn)
        self._bind_recursive(self, "<Button-3>",        self._show_menu, skip=self._del_btn)
        self._bind_recursive(self, "<Enter>", lambda _: self.configure(fg_color=C["card_hover"]))
        self._bind_recursive(self, "<Leave>", lambda _: self.configure(fg_color=C["card"]))

    def _bind_recursive(self, widget, sequence: str, callback, skip=None) -> None:
        if widget is skip:
            return
        widget.bind(sequence, callback)
        for child in widget.winfo_children():
            self._bind_recursive(child, sequence, callback, skip=skip)

    def _handle_delete(self) -> None:
        if self._on_delete:
            self._on_delete(self._record)

    def _open_file(self, _event=None) -> None:
        if self._record.path:
            _open_in_file_manager(Path(self._record.path))

    def _show_menu(self, event) -> None:
        menu = tk.Menu(self, tearoff=0,
                       bg=C["card"], fg=C["text"],
                       activebackground=C["accent"], activeforeground="#000",
                       borderwidth=0)
        has_path = bool(self._record.path) and Path(self._record.path).exists()
        menu.add_command(label="Abrir archivo",
                         command=self._open_file,
                         state="normal" if has_path else "disabled")
        menu.add_command(label="Abrir carpeta",
                         command=lambda: _open_in_file_manager(Path(self._record.path).parent)
                         if self._record.path else None,
                         state="normal" if has_path else "disabled")
        menu.add_separator()
        menu.add_command(label="Copiar ruta",
                         command=lambda: _copy_to_clipboard(self.winfo_toplevel(), self._record.path),
                         state="normal" if self._record.path else "disabled")
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()


# ─────────────────────────────────────────────────────────────────────────────
# Dashboard
# ─────────────────────────────────────────────────────────────────────────────

class DashboardPanel(ctk.CTkFrame):
    """Overview: stat cards, platform breakdown, recent downloads."""

    def __init__(self, parent, history: HistoryManager, **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=0, **kw)
        self._history = history
        self._cards: Dict[str, StatCard] = {}
        self._plat_frame: Optional[ctk.CTkFrame] = None
        self._recent_frame: Optional[ctk.CTkFrame] = None
        self._build()

    def _build(self) -> None:
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        scrollbar_button_color=C["border"])
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        SectionLabel(scroll, "Resumen").pack(anchor="w", pady=(0, 10))

        cards_row = ctk.CTkFrame(scroll, fg_color="transparent")
        cards_row.pack(fill="x", pady=(0, 16))
        for col in range(4):
            cards_row.columnconfigure(col, weight=1)

        defs = [
            ("today",   "0",  "Hoy",        C["accent"]),
            ("total",   "0",  "Total",       C["text_mid"]),
            ("queue",   "0",  "En cola",     C["warning"]),
            ("success", "0%", "Tasa éxito",  C["success"]),
        ]
        for col, (key, val, label, color) in enumerate(defs):
            card = StatCard(cards_row, val, label, color=color)
            card.grid(row=0, column=col, padx=(0 if col == 0 else 8, 0), sticky="ew")
            self._cards[key] = card

        mid = ctk.CTkFrame(scroll, fg_color="transparent")
        mid.pack(fill="x", pady=(0, 16))
        mid.columnconfigure(0, weight=1)
        mid.columnconfigure(1, weight=1)

        plat_card = ctk.CTkFrame(mid, fg_color=C["card"], corner_radius=8)
        plat_card.grid(row=0, column=0, padx=(0, 8), sticky="nsew")
        ctk.CTkLabel(plat_card, text="PLATAFORMAS", font=_font(9, "bold"),
                     text_color=C["text_dim"]).pack(anchor="w", padx=14, pady=(12, 8))
        self._plat_frame = ctk.CTkFrame(plat_card, fg_color="transparent")
        self._plat_frame.pack(fill="x", padx=14, pady=(0, 12))

        recent_card = ctk.CTkFrame(mid, fg_color=C["card"], corner_radius=8)
        recent_card.grid(row=0, column=1, padx=(8, 0), sticky="nsew")
        ctk.CTkLabel(recent_card, text="ÚLTIMAS DESCARGAS", font=_font(9, "bold"),
                     text_color=C["text_dim"]).pack(anchor="w", padx=14, pady=(12, 8))
        self._recent_frame = ctk.CTkFrame(recent_card, fg_color="transparent")
        self._recent_frame.pack(fill="x", padx=14, pady=(0, 12))

        self.refresh()

    def refresh(self) -> None:
        """Reload stats from history."""
        stats = self._history.stats()
        self._cards["today"].update_value(str(stats["today"]))
        self._cards["total"].update_value(str(stats["total"]))
        self._cards["success"].update_value(
            f"{stats['success_pct']}%",
            C["success"] if stats["success_pct"] >= 90 else C["warning"])

        # Platform bars
        if self._plat_frame:
            for w in self._plat_frame.winfo_children():
                w.destroy()
            total = max(stats["total"], 1)
            for plat, sym in [("spotify", "Spotify"), ("applemusic", "Apple"), ("soundcloud", "SoundCl.")]:
                n     = stats["by_platform"].get(plat, 0)
                pct   = n / total
                color = PLATFORM_COLORS.get(plat, C["text_dim"])
                row   = ctk.CTkFrame(self._plat_frame, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text=sym, font=_font(9), text_color=C["text_mid"],
                             width=60, anchor="w").pack(side="left")
                bar = ctk.CTkProgressBar(row, height=6, fg_color=C["border"],
                                         progress_color=color, corner_radius=3, width=100)
                bar.pack(side="left", padx=(4, 8))
                bar.set(pct)
                ctk.CTkLabel(row, text=str(n), font=_font(9, mono=True),
                             text_color=C["text_dim"]).pack(side="left")

        # Recent downloads
        if self._recent_frame:
            for w in self._recent_frame.winfo_children():
                w.destroy()
            recent = self._history.recent(6)
            if not recent:
                ctk.CTkLabel(self._recent_frame, text="Sin historial aún",
                             font=_font(10), text_color=C["text_dim"]).pack(anchor="w")
            for r in recent:
                ok  = r.status == "done"
                row = ctk.CTkFrame(self._recent_frame, fg_color="transparent")
                row.pack(fill="x", pady=2)
                ctk.CTkLabel(row, text="✓" if ok else "✕",
                             font=_font(10, "bold"),
                             text_color=C["success"] if ok else C["error"],
                             width=18).pack(side="left")
                name = f"{r.artist} — {r.title}"
                ctk.CTkLabel(row, text=name[:42], font=_font(10),
                             text_color=C["text"], anchor="w").pack(side="left", padx=(4, 0))

    def update_queue_count(self, n: int) -> None:
        self._cards["queue"].update_value(str(n), C["warning"] if n else C["text_dim"])


# ─────────────────────────────────────────────────────────────────────────────
# Search panel
# ─────────────────────────────────────────────────────────────────────────────

class SearchPanel(ctk.CTkFrame):
    _PLATFORMS    = ["auto", "spotify", "applemusic", "soundcloud"]
    _PLAT_DISPLAY = {"auto": "Todas", "spotify": "Spotify",
                     "applemusic": "Apple Music", "soundcloud": "SoundCloud"}

    def __init__(self, parent, controller: AppController,
                 on_add_track: Callable, **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=0, **kw)
        self._ctrl         = controller
        self._on_add_track = on_add_track
        self._results: List[ctk.CTkFrame] = []
        self._last_results: List[TrackInfo] = []
        self._searching    = False
        self._platform_var = ctk.StringVar(value="auto")
        self._chip_btns: Dict[str, ctk.CTkButton] = {}
        self._build()

    def _build(self) -> None:
        # Search bar
        bar = ctk.CTkFrame(self, fg_color=C["surface"], corner_radius=10)
        bar.pack(fill="x", padx=20, pady=(20, 0))

        self._search_var = ctk.StringVar()
        self._entry = ctk.CTkEntry(
            bar, textvariable=self._search_var,
            placeholder_text="URL de Spotify / Apple Music / SoundCloud, o artista — canción…",
            font=_font(12), fg_color="transparent",
            border_width=0, height=46, text_color=C["text"])
        self._entry.pack(side="left", fill="x", expand=True, padx=(14, 0), pady=6)
        self._entry.bind("<Return>",  lambda _: self._do_search())
        self._entry.bind("<Escape>",  lambda _: self._clear_entry())

        self._search_var.trace_add("write", self._on_query_change)

        self._clear_btn = ctk.CTkButton(
            bar, text="✕", width=28, height=28, font=_font(10),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text_dim"], corner_radius=5, command=self._clear_entry)

        self._search_btn = ctk.CTkButton(
            bar, text="Buscar", width=90, height=36,
            font=_font(12, "bold"), fg_color=C["accent"],
            hover_color=C["accent_dim"], text_color="#000",
            corner_radius=7, command=self._do_search)
        self._search_btn.pack(side="right", padx=8, pady=6)

        # Platform filter chips
        frow = ctk.CTkFrame(self, fg_color="transparent")
        frow.pack(fill="x", padx=20, pady=(10, 0))

        for plat in self._PLATFORMS:
            active = plat == "auto"
            color  = PLATFORM_COLORS.get(plat, C["accent"]) if plat != "auto" else C["accent"]
            btn    = ctk.CTkButton(
                frow, text=self._PLAT_DISPLAY[plat], width=0, height=26,
                font=_font(10, "bold"), corner_radius=13,
                fg_color=color if active else C["surface"],
                hover_color=C["card_hover"],
                text_color="#000" if active else C["text_mid"],
                border_width=1,
                border_color=color if active else C["border"],
                command=lambda p=plat: self._set_platform(p))
            btn.pack(side="left", padx=(0, 6))
            self._chip_btns[plat] = btn

        self._view_var = ctk.StringVar(value="Cuadrícula")
        ctk.CTkSegmentedButton(
            frow, values=["Lista", "Cuadrícula"],
            variable=self._view_var, font=_font(10),
            fg_color=C["surface"],
            selected_color=C["border_focus"],
            selected_hover_color=C["border_focus"],
            unselected_color=C["surface"],
            unselected_hover_color=C["card_hover"],
            text_color=C["text"],
            command=lambda _: self._rerender()).pack(side="right")

        # Duration filter
        dur_row = ctk.CTkFrame(self, fg_color="transparent")
        dur_row.pack(fill="x", padx=20, pady=(8, 0))

        ctk.CTkLabel(dur_row, text="Duración:", font=_font(9),
                     text_color=C["text_dim"]).pack(side="left", padx=(0, 8))
        self._dur_min_var = ctk.StringVar(value="0:00")
        self._dur_max_var = ctk.StringVar(value="Cualquiera")
        for lbl, var, vals in [
            ("Min", self._dur_min_var, ["0:00", "1:00", "2:00", "3:00", "4:00"]),
            ("Max", self._dur_max_var, ["Cualquiera", "4:00", "6:00", "8:00", "10:00", "15:00"]),
        ]:
            ctk.CTkLabel(dur_row, text=lbl, font=_font(9),
                         text_color=C["text_dim"]).pack(side="left", padx=(0, 4))
            ctk.CTkOptionMenu(dur_row, values=vals, variable=var,
                              fg_color=C["surface"], button_color=C["border"],
                              dropdown_fg_color=C["card"], font=_font(9),
                              text_color=C["text"], width=90, height=24).pack(side="left", padx=(0, 10))

        self._status_lbl = ctk.CTkLabel(self, text="", font=_font(10),
                                        text_color=C["text_dim"], anchor="w")
        self._status_lbl.pack(fill="x", padx=22, pady=(8, 0))

        self._results_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["border_focus"])
        self._results_frame.pack(fill="both", expand=True, padx=20, pady=(4, 20))

        self._empty_lbl = ctk.CTkLabel(
            self._results_frame, text="",
            font=_font(13), text_color=C["text_dim"], justify="center")

    # ── Internal ──────────────────────────────────────────────────────────────

    def _on_query_change(self, *_) -> None:
        if self._search_var.get():
            self._clear_btn.pack(side="right", padx=(0, 2), pady=6)
        else:
            self._clear_btn.pack_forget()

    def _clear_entry(self) -> None:
        self._search_var.set("")
        self._status_lbl.configure(text="")
        self._clear_results()
        self._entry.focus()

    def focus_search(self) -> None:
        self._entry.focus()

    def _set_platform(self, plat: str) -> None:
        self._platform_var.set(plat)
        for p, btn in self._chip_btns.items():
            color  = PLATFORM_COLORS.get(p, C["accent"]) if p != "auto" else C["accent"]
            active = p == plat
            btn.configure(
                fg_color=color if active else C["surface"],
                text_color="#000" if active else C["text_mid"],
                border_color=color if active else C["border"])

    def _do_search(self) -> None:
        query = self._search_var.get().strip()
        if not query or self._searching:
            return
        self._searching = True
        self._search_btn.configure(state="disabled", text="·")
        self._status_lbl.configure(text="Buscando…", text_color=C["accent"])
        self._clear_results()
        platform = self._platform_var.get()
        self._animate_btn()

        def _worker() -> None:
            try:
                if query.startswith(("http://", "https://")):
                    self.after(0, lambda: self._status_lbl.configure(
                        text="Cargando URL…", text_color=C["accent"]))
                    results = self._ctrl.resolve_url(query)
                else:
                    results = self._ctrl.search(query, platform_str=platform)
                results = self._apply_duration_filter(results)
                self.after(0, lambda: self._show_results(results))
            except Exception as exc:
                self.after(0, lambda: self._status_lbl.configure(
                    text=f"Error: {exc}", text_color=C["error"]))
            finally:
                self.after(0, lambda: (
                    self._search_btn.configure(state="normal", text="Buscar"),
                    setattr(self, "_searching", False)))

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_duration_filter(self, results: List[TrackInfo]) -> List[TrackInfo]:
        def _to_ms(s: str) -> int:
            try:
                m, sec = s.split(":")
                return (int(m) * 60 + int(sec)) * 1000
            except Exception:
                return 0

        mn = _to_ms(self._dur_min_var.get())
        mx = _to_ms(self._dur_max_var.get()) if self._dur_max_var.get() != "Cualquiera" else 999_999_999
        if mn == 0 and mx == 999_999_999:
            return results
        return [t for t in results if mn <= t.duration_ms <= mx or t.duration_ms == 0]

    def _animate_btn(self) -> None:
        frames = ["·", "··", "···", "··"]
        idx = getattr(self, "_anim_idx", 0)
        if self._searching:
            self._search_btn.configure(text=frames[idx % 4])
            self._anim_idx = idx + 1
            self.after(220, self._animate_btn)
        else:
            self._anim_idx = 0

    def _get_grid_cols(self) -> int:
        """Calculate number of grid columns from available panel width."""
        self._results_frame.update_idletasks()
        w = self._results_frame.winfo_width()
        if w < 10:
            w = 720   # safe default before widget is fully drawn
        cols = max(2, w // (TrackCard._CARD_W + 12))
        return min(cols, 5)

    def _show_results(self, results: List[TrackInfo]) -> None:
        self._last_results = list(results)
        self._clear_results()
        if not results:
            diag = self._ctrl.search_diagnostics()
            hint = f"  ({'; '.join(diag)})" if diag else ""
            self._status_lbl.configure(text=f"Sin resultados.{hint}",
                                       text_color=C["text_dim"])
            self._empty_lbl.configure(text="♪\n\nSin resultados para esta búsqueda.")
            self._empty_lbl.pack(expand=True, pady=50)
            return

        from collections import Counter
        counts = Counter(t.platform for t in results)
        parts  = []
        for plat, sym in [("spotify", "SP"), ("applemusic", "AM"), ("soundcloud", "SC")]:
            if counts.get(plat, 0):
                parts.append(f"{sym} {counts[plat]}")
        breakdown = "  ·  " + "  ".join(parts) if parts else ""
        n = len(results)
        self._status_lbl.configure(
            text=f"{n} resultado{'s' if n != 1 else ''}{breakdown}  —  + para añadir",
            text_color=C["success"])

        BATCH     = 20
        grid_mode = self._view_var.get() == "Cuadrícula"
        cols      = self._get_grid_cols() if grid_mode else 1

        if grid_mode:
            for c in range(cols):
                self._results_frame.grid_columnconfigure(c, weight=1)

        def _render(offset: int) -> None:
            batch = results[offset: offset + BATCH]
            if not batch:
                return
            for i, track in enumerate(batch):
                idx = offset + i
                if grid_mode:
                    card = TrackCard(self._results_frame, track, on_add=self._add_track)
                    card.grid(row=idx // cols, column=idx % cols, padx=4, pady=4, sticky="n")
                    self._results.append(card)
                else:
                    row = TrackRow(self._results_frame, track, on_add=self._add_track)
                    row.pack(fill="x", pady=(0, 3))
                    self._results.append(row)
            if offset + BATCH < len(results):
                self.after(10, lambda: _render(offset + BATCH))

        _render(0)

    def _rerender(self) -> None:
        if self._last_results:
            self._show_results(self._last_results)

    def _add_track(self, track: TrackInfo) -> None:
        for w in self._results:
            if getattr(w, "_track", None) is track:
                w.flash()
                break
        self._on_add_track(track)

    def _clear_results(self) -> None:
        self._empty_lbl.pack_forget()
        for w in list(self._results_frame.winfo_children()):
            if w is not self._empty_lbl:
                w.destroy()
        self._results.clear()


# ─────────────────────────────────────────────────────────────────────────────
# Download panel
# ─────────────────────────────────────────────────────────────────────────────

class DownloadPanel(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController, history: HistoryManager,
                 on_count_change: Optional[Callable] = None,
                 on_task_complete: Optional[Callable] = None, **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=0, **kw)
        self._ctrl            = controller
        self._history         = history
        self._on_count_change = on_count_change
        self._on_task_complete = on_task_complete
        self._rows: Dict[str, QueueRow] = {}
        self._completed_ids: set = set()   # tracks for which we've already fired on_task_complete
        self._build()

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(20, 0))

        ctk.CTkLabel(hdr, text="COLA DE DESCARGA", font=_font(10, "bold"),
                     text_color=C["text_dim"]).pack(side="left")
        self._counter = ctk.CTkLabel(hdr, text="", font=_font(10), text_color=C["accent"])
        self._counter.pack(side="left", padx=(8, 0))

        ctk.CTkButton(hdr, text="Limpiar terminados", width=130, height=26, font=_font(9),
                      fg_color=C["surface"], hover_color=C["card_hover"],
                      text_color=C["text_mid"], corner_radius=5,
                      command=self._clear_done).pack(side="right")

        Divider(self).pack(fill="x", padx=20, pady=(10, 0))

        self._empty_lbl = ctk.CTkLabel(
            self,
            text="↓\n\nLa cola está vacía\nAñade canciones desde  Buscar",
            font=_font(12), text_color=C["text_dim"], justify="center")
        self._empty_lbl.pack(expand=True)

        self._list = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["border_focus"])
        self._list_visible = False

    def on_task_update(self, task: DownloadTask) -> None:
        """Called by the controller from a background thread."""
        self.after(0, lambda: self._update_ui(task))

    def populate_from_existing(self, tasks: List[DownloadTask]) -> None:
        """Re-populate rows from an existing task list (e.g. after theme rebuild)."""
        for task in tasks:
            if task.task_id not in self._rows:
                self._update_ui(task)

    def _update_ui(self, task: DownloadTask) -> None:
        tid = task.task_id
        if tid not in self._rows:
            if not self._list_visible:
                self._empty_lbl.pack_forget()
                self._list.pack(fill="both", expand=True, padx=20, pady=(8, 20))
                self._list_visible = True
            row = QueueRow(self._list, task, on_remove=self._remove)
            row.pack(fill="x", pady=(0, 3))
            self._rows[tid] = row
        else:
            self._rows[tid].update_task(task)

        if task.status in (DownloadStatus.DONE, DownloadStatus.ERROR):
            self._history.add_from_task(task)

        # Fire the completion callback exactly once per task.
        if task.status == DownloadStatus.DONE and task.task_id not in self._completed_ids:
            self._completed_ids.add(task.task_id)
            if self._on_task_complete:
                try:
                    self._on_task_complete(task)
                except Exception:
                    pass

        self._refresh_counter()

    def _remove(self, task: DownloadTask) -> None:
        self._ctrl.remove_from_queue(task)
        tid = task.task_id
        if tid in self._rows:
            self._rows[tid].destroy()
            del self._rows[tid]
        if not self._rows:
            self._list.pack_forget()
            self._list_visible = False
            self._empty_lbl.pack(expand=True)
        self._refresh_counter()

    def _clear_done(self) -> None:
        self._ctrl.clear_completed()
        terminal = {DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED}
        for tid in list(self._rows):
            if self._rows[tid]._task.status in terminal:
                self._rows[tid].destroy()
                del self._rows[tid]
        if not self._rows:
            self._list.pack_forget()
            self._list_visible = False
            self._empty_lbl.pack(expand=True)
        self._refresh_counter()

    def _refresh_counter(self) -> None:
        total  = len(self._rows)
        done   = sum(1 for r in self._rows.values() if r._task.status == DownloadStatus.DONE)
        active = sum(1 for r in self._rows.values() if r._task.status in (
            DownloadStatus.DOWNLOADING, DownloadStatus.SEARCHING, DownloadStatus.PROCESSING))
        if total:
            self._counter.configure(text=f"{done}/{total} completados  ·  {active} activos")
        else:
            self._counter.configure(text="")
        if self._on_count_change:
            pending = sum(1 for r in self._rows.values() if r._task.status not in (
                DownloadStatus.DONE, DownloadStatus.ERROR, DownloadStatus.CANCELLED))
            self._on_count_change(pending)


# ─────────────────────────────────────────────────────────────────────────────
# History panel
# ─────────────────────────────────────────────────────────────────────────────

class HistoryPanel(ctk.CTkFrame):
    PAGE_SIZE = 40

    def __init__(self, parent, history: HistoryManager,
                 on_dashboard_refresh: Optional[Callable] = None, **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=0, **kw)
        self._history              = history
        self._on_dashboard_refresh = on_dashboard_refresh
        self._page                 = 0
        self._total                = 0
        self._build()

    def _build(self) -> None:
        hdr = ctk.CTkFrame(self, fg_color="transparent")
        hdr.pack(fill="x", padx=20, pady=(20, 0))

        self._count_lbl = ctk.CTkLabel(hdr, text="HISTORIAL", font=_font(10, "bold"),
                                       text_color=C["text_dim"])
        self._count_lbl.pack(side="left")

        ctk.CTkButton(hdr, text="JSON", width=50, height=26, font=_font(9),
                      fg_color=C["surface"], hover_color=C["card_hover"],
                      text_color=C["text_mid"], corner_radius=5,
                      command=self._export_json).pack(side="right", padx=(4, 0))
        ctk.CTkButton(hdr, text="CSV", width=50, height=26, font=_font(9),
                      fg_color=C["surface"], hover_color=C["card_hover"],
                      text_color=C["text_mid"], corner_radius=5,
                      command=self._export_csv).pack(side="right")

        filters = ctk.CTkFrame(self, fg_color="transparent")
        filters.pack(fill="x", padx=20, pady=(8, 0))

        self._search_var = ctk.StringVar()
        self._search_var.trace_add("write", lambda *_: self._reload(reset=True))
        ctk.CTkEntry(filters, textvariable=self._search_var,
                     placeholder_text="Buscar en historial…",
                     font=_font(11), fg_color=C["surface"],
                     border_color=C["border"], border_width=1,
                     text_color=C["text"], height=32).pack(
                         side="left", fill="x", expand=True, padx=(0, 8))

        self._plat_var = ctk.StringVar(value="Todas")
        ctk.CTkOptionMenu(filters, values=["Todas", "Spotify", "Apple Music", "SoundCloud"],
                          variable=self._plat_var, fg_color=C["surface"],
                          button_color=C["border"], dropdown_fg_color=C["card"],
                          font=_font(10), text_color=C["text"], width=130, height=32,
                          command=lambda _: self._reload(reset=True)).pack(side="left", padx=(0, 8))

        self._status_var = ctk.StringVar(value="Todos")
        ctk.CTkOptionMenu(filters, values=["Todos", "Completados", "Errores"],
                          variable=self._status_var, fg_color=C["surface"],
                          button_color=C["border"], dropdown_fg_color=C["card"],
                          font=_font(10), text_color=C["text"], width=110, height=32,
                          command=lambda _: self._reload(reset=True)).pack(side="left")

        Divider(self).pack(fill="x", padx=20, pady=(10, 0))

        self._list = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["border_focus"])
        self._list.pack(fill="both", expand=True, padx=20, pady=(6, 0))

        self._empty_lbl = ctk.CTkLabel(
            self._list, text="≡\n\nSin historial todavía.",
            font=_font(13), text_color=C["text_dim"], justify="center")

        pg = ctk.CTkFrame(self, fg_color="transparent")
        pg.pack(fill="x", padx=20, pady=(6, 12))

        self._prev_btn = ctk.CTkButton(pg, text="← Anterior", width=100, height=28,
                                       font=_font(9), fg_color=C["surface"],
                                       hover_color=C["card_hover"], text_color=C["text_mid"],
                                       corner_radius=5, command=self._prev_page)
        self._prev_btn.pack(side="left")

        self._page_lbl = ctk.CTkLabel(pg, text="", font=_font(9), text_color=C["text_dim"])
        self._page_lbl.pack(side="left", padx=16)

        self._next_btn = ctk.CTkButton(pg, text="Siguiente →", width=100, height=28,
                                       font=_font(9), fg_color=C["surface"],
                                       hover_color=C["card_hover"], text_color=C["text_mid"],
                                       corner_radius=5, command=self._next_page)
        self._next_btn.pack(side="right")

        self._reload()

    def _reload(self, reset: bool = False) -> None:
        if reset:
            self._page = 0

        plat_map   = {"Todas": "", "Spotify": "spotify",
                      "Apple Music": "applemusic", "SoundCloud": "soundcloud"}
        status_map = {"Todos": "", "Completados": "done", "Errores": "error"}

        records, total = self._history.filter(
            query    = self._search_var.get().strip(),
            platform = plat_map.get(self._plat_var.get(), ""),
            status   = status_map.get(self._status_var.get(), ""),
            page     = self._page,
            page_size = self.PAGE_SIZE,
        )
        self._total = total

        for w in list(self._list.winfo_children()):
            if w is not self._empty_lbl:
                w.destroy()

        if not records:
            self._empty_lbl.pack(expand=True, pady=40)
        else:
            self._empty_lbl.pack_forget()
            for rec in records:
                HistoryRow(self._list, rec, on_delete=self._delete_record).pack(
                    fill="x", pady=(0, 3))

        pages = max(1, (total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        self._count_lbl.configure(text=f"HISTORIAL  ·  {total} tracks")
        self._page_lbl.configure(text=f"Pág. {self._page + 1} / {pages}")
        self._prev_btn.configure(state="normal" if self._page > 0 else "disabled")
        self._next_btn.configure(state="normal" if self._page < pages - 1 else "disabled")

    def refresh(self) -> None:
        self._reload()

    def _delete_record(self, record) -> None:
        """Remove one record from the history and refresh the view."""
        if self._history.delete(record.id):
            # If the current page is now empty (last item removed), step back.
            self._reload()
            if self._on_dashboard_refresh:
                self._on_dashboard_refresh()

    def _prev_page(self) -> None:
        if self._page > 0:
            self._page -= 1
            self._reload()

    def _next_page(self) -> None:
        pages = max(1, (self._total + self.PAGE_SIZE - 1) // self.PAGE_SIZE)
        if self._page < pages - 1:
            self._page += 1
            self._reload()

    def _export_csv(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", filetypes=[("CSV", "*.csv")],
            initialfile="dj_tracks_historial.csv")
        if path:
            self._history.export_csv(Path(path))

    def _export_json(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".json", filetypes=[("JSON", "*.json")],
            initialfile="dj_tracks_historial.json")
        if path:
            self._history.export_json(Path(path))


# ─────────────────────────────────────────────────────────────────────────────
# Settings panel
# ─────────────────────────────────────────────────────────────────────────────

class SettingsPanel(ctk.CTkFrame):
    def __init__(self, parent, controller: AppController,
                 on_save: Optional[Callable] = None,
                 on_theme_change: Optional[Callable] = None,
                 on_clear_history: Optional[Callable] = None,
                 on_clear_cover_cache: Optional[Callable] = None,
                 on_reset_config: Optional[Callable] = None,
                 **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=0, **kw)
        self._ctrl                 = controller
        self._on_save              = on_save
        self._on_theme_change      = on_theme_change
        self._on_clear_history     = on_clear_history
        self._on_clear_cover_cache = on_clear_cover_cache
        self._on_reset_config      = on_reset_config
        self._build()

    def _build(self) -> None:
        scroll = ctk.CTkScrollableFrame(self, fg_color="transparent",
                                        scrollbar_button_color=C["border"])
        scroll.pack(fill="both", expand=True, padx=20, pady=20)

        # ── Theme selector ────────────────────────────────────────────────────
        SectionLabel(scroll, "Tema Visual").pack(anchor="w", pady=(0, 8))
        theme_card = self._card(scroll)

        ctk.CTkLabel(theme_card, text="Selecciona tu estilo preferido",
                     font=_font(10), text_color=C["text_mid"]).pack(anchor="w", padx=14, pady=(12, 8))

        self._theme_var = ctk.StringVar(value=self._ctrl.get_config("theme", "Dark Pro"))

        theme_grid = ctk.CTkFrame(theme_card, fg_color="transparent")
        theme_grid.pack(fill="x", padx=14, pady=(0, 14))

        _THEME_ACCENTS = {
            "Dark Pro":     "#00C8FF",
            "Neon Blue":    "#1E90FF",
            "Neon Purple":  "#A020FF",
            "Carbon Black": "#FF6B00",
        }
        _THEME_BG = {
            "Dark Pro":     "#08080F",
            "Neon Blue":    "#020208",
            "Neon Purple":  "#06020C",
            "Carbon Black": "#080808",
        }
        for col, name in enumerate(_THEME_ACCENTS):
            accent = _THEME_ACCENTS[name]
            bg     = _THEME_BG[name]
            btn = ctk.CTkButton(
                theme_grid, text=name, width=0, height=36, font=_font(10, "bold"),
                fg_color=bg, hover_color=accent + "44",
                text_color=accent, border_width=2,
                border_color=accent if self._theme_var.get() == name else C["border"],
                corner_radius=6,
                command=lambda n=name: self._select_theme(n))
            btn.grid(row=0, column=col, padx=(0 if col == 0 else 6, 0), sticky="ew")
            theme_grid.columnconfigure(col, weight=1)
            btn._theme_name   = name
            btn._theme_accent = accent
        self._theme_grid = theme_grid

        # ── Download settings ─────────────────────────────────────────────────
        SectionLabel(scroll, "Descarga").pack(anchor="w", pady=(16, 8))
        dl_card = self._card(scroll)

        self._field_lbl(dl_card, "Carpeta de destino")
        fr = ctk.CTkFrame(dl_card, fg_color="transparent")
        fr.pack(fill="x", padx=14, pady=(0, 14))
        self._folder_var = ctk.StringVar(value=self._ctrl.get_config("download_folder", "downloads"))
        ctk.CTkEntry(fr, textvariable=self._folder_var, font=_font(11),
                     fg_color=C["surface"], border_color=C["border"],
                     border_width=1, text_color=C["text"], height=34).pack(
                         side="left", fill="x", expand=True, padx=(0, 8))
        ctk.CTkButton(fr, text="···", width=44, height=34, font=_font(12),
                      fg_color=C["border"], hover_color=C["border_focus"],
                      text_color=C["text"], corner_radius=6,
                      command=self._browse).pack(side="left")

        Divider(dl_card).pack(fill="x", padx=14, pady=2)

        fq = ctk.CTkFrame(dl_card, fg_color="transparent")
        fq.pack(fill="x", padx=14, pady=(8, 14))
        self._fmt_var  = ctk.StringVar(value=self._ctrl.get_config("preferred_format",  "mp3"))
        self._qual_var = ctk.StringVar(value=self._ctrl.get_config("preferred_quality", "320k"))
        for lbl, var, vals in [
            ("Formato", self._fmt_var,  ["mp3", "flac", "wav", "best"]),
            ("Calidad",  self._qual_var, ["128k", "192k", "320k", "best"]),
        ]:
            col = ctk.CTkFrame(fq, fg_color="transparent")
            col.pack(side="left", expand=True, fill="x", padx=(0, 12))
            ctk.CTkLabel(col, text=lbl, font=_font(10), text_color=C["text_mid"]).pack(anchor="w")
            ctk.CTkOptionMenu(col, values=vals, variable=var,
                              fg_color=C["surface"], button_color=C["border"],
                              button_hover_color=C["border_focus"],
                              dropdown_fg_color=C["card"], dropdown_hover_color=C["card_hover"],
                              font=_font(11), text_color=C["text"], height=34).pack(fill="x", pady=(4, 0))

        Divider(dl_card).pack(fill="x", padx=14, pady=2)
        self._field_lbl(dl_card, "Estructura de carpetas")
        self._struct_var = ctk.StringVar(
            value=self._ctrl.get_config("folder_structure", "{artist}/{album}/{artist} - {title}"))
        ctk.CTkEntry(dl_card, textvariable=self._struct_var, font=_font(11, mono=True),
                     fg_color=C["surface"], border_color=C["border"],
                     border_width=1, text_color=C["text"], height=34).pack(
                         fill="x", padx=14, pady=(0, 4))
        ctk.CTkLabel(dl_card,
                     text="Variables:  {artist}   {album}   {title}   {year}",
                     font=_font(9), text_color=C["text_dim"]).pack(anchor="w", padx=14, pady=(0, 14))

        Divider(dl_card).pack(fill="x", padx=14, pady=2)

        # Behaviour toggles
        self._auto_fix_var      = ctk.BooleanVar(value=self._ctrl.get_config("auto_fix_metadata", True))
        self._subfolder_var     = ctk.BooleanVar(value=self._ctrl.get_config("subfolder_per_platform", False))
        self._switch_row(dl_card, "Auto-arreglar metadatos",
                         "Corrige título / artista / álbum tras la descarga",
                         self._auto_fix_var)
        self._switch_row(dl_card, "Sub-carpeta por plataforma",
                         "Crea carpetas separadas: Spotify / Apple Music / SoundCloud",
                         self._subfolder_var)

        # Parallel downloads
        Divider(dl_card).pack(fill="x", padx=14, pady=2)
        threads_row = ctk.CTkFrame(dl_card, fg_color="transparent")
        threads_row.pack(fill="x", padx=14, pady=(8, 14))
        ctk.CTkLabel(threads_row, text="Descargas paralelas",
                     font=_font(11, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(threads_row, text="Cuántas pistas pueden descargarse a la vez (1–4)",
                     font=_font(9), text_color=C["text_dim"]).pack(anchor="w")
        self._threads_var = ctk.StringVar(value=str(self._ctrl.get_config("threads", 2)))
        ctk.CTkOptionMenu(
            threads_row, values=["1", "2", "3", "4"], variable=self._threads_var,
            fg_color=C["surface"], button_color=C["border"],
            button_hover_color=C["border_focus"],
            dropdown_fg_color=C["card"], dropdown_hover_color=C["card_hover"],
            font=_font(11), text_color=C["text"], width=70, height=30,
        ).pack(anchor="w", pady=(6, 0))

        # ── Notifications ─────────────────────────────────────────────────────
        SectionLabel(scroll, "Notificaciones").pack(anchor="w", pady=(16, 8))
        notif_card = self._card(scroll)

        self._notify_var       = ctk.BooleanVar(value=self._ctrl.get_config("notify_on_complete", True))
        self._open_folder_var  = ctk.BooleanVar(value=self._ctrl.get_config("open_folder_on_complete", False))
        self._sound_var        = ctk.BooleanVar(value=self._ctrl.get_config("sound_on_complete", False))

        self._switch_row(notif_card, "Mostrar aviso al completar",
                         "Burbuja flotante cuando cada descarga termina",
                         self._notify_var)
        self._switch_row(notif_card, "Abrir carpeta al completar",
                         "Lanza el Explorador en la carpeta del archivo",
                         self._open_folder_var)
        self._switch_row(notif_card, "Sonido al completar",
                         "Pitido del sistema cuando termina cada descarga",
                         self._sound_var)

        # ── API Credentials ───────────────────────────────────────────────────
        SectionLabel(scroll, "Credenciales de API").pack(anchor="w", pady=(16, 8))
        api_card = self._card(scroll)
        sp_cfg   = self._ctrl.get_config("spotify",    {})
        sc_cfg   = self._ctrl.get_config("soundcloud", {})

        for i, (label, attr, default, secret) in enumerate([
            ("Spotify  ·  Client ID",     "_sp_id_var",     sp_cfg.get("client_id", ""),     False),
            ("Spotify  ·  Client Secret", "_sp_secret_var", sp_cfg.get("client_secret", ""), True),
            ("SoundCloud  ·  Client ID",  "_sc_id_var",     sc_cfg.get("client_id", ""),     False),
        ]):
            if i:
                Divider(api_card).pack(fill="x", padx=14, pady=2)
            self._field_lbl(api_card, label)
            var = ctk.StringVar(value=default)
            setattr(self, attr, var)
            ctk.CTkEntry(api_card, textvariable=var, show="●" if secret else "",
                         font=_font(11), fg_color=C["surface"],
                         border_color=C["border"], border_width=1,
                         text_color=C["text"], height=34).pack(fill="x", padx=14, pady=(0, 14))

        ctk.CTkLabel(scroll, font=_font(10), text_color=C["text_dim"], justify="left",
                     text="Apple Music: iTunes Search API pública, sin credenciales.\n"
                          "SoundCloud: detecta Client ID automáticamente.").pack(
                              anchor="w", pady=(8, 16))

        # ── Mantenimiento ─────────────────────────────────────────────────────
        SectionLabel(scroll, "Mantenimiento").pack(anchor="w", pady=(0, 8))
        maint_card = self._card(scroll)

        cache_n = _COVER_CACHE.size()
        self._maint_button(
            maint_card,
            label=f"Limpiar caché de imágenes",
            hint=f"Libera la memoria usada por las {cache_n} portadas en caché",
            command=self._handle_clear_cache)
        Divider(maint_card).pack(fill="x", padx=14, pady=2)
        self._maint_button(maint_card,
                           label="Borrar historial de descargas",
                           hint="Elimina todos los registros del historial",
                           command=self._handle_clear_history,
                           danger=True)
        Divider(maint_card).pack(fill="x", padx=14, pady=2)
        self._maint_button(maint_card,
                           label="Restablecer ajustes",
                           hint="Vuelve a los valores por defecto (las credenciales se conservan)",
                           command=self._handle_reset_config,
                           danger=True)

        # ── Save button ───────────────────────────────────────────────────────
        self._save_btn = ctk.CTkButton(
            scroll, text="Guardar configuración",
            height=44, font=_font(13, "bold"),
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color="#000", corner_radius=8, command=self._save)
        self._save_btn.pack(fill="x", pady=(16, 0))

    # ── Reusable building blocks ──────────────────────────────────────────────

    def _switch_row(self, parent, label: str, hint: str, var: ctk.BooleanVar) -> None:
        """Render a toggle row: label + hint on the left, switch on the right."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=8)

        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=label, font=_font(11, "bold"),
                     text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(text_col, text=hint, font=_font(9),
                     text_color=C["text_dim"], anchor="w").pack(fill="x")

        ctk.CTkSwitch(
            row, text="", variable=var, onvalue=True, offvalue=False,
            progress_color=C["accent"], button_color=C["text"],
            button_hover_color=C["text_mid"], fg_color=C["surface"],
            width=44, height=22,
        ).pack(side="right", padx=(8, 0))

    def _maint_button(self, parent, label: str, hint: str,
                      command: Callable, danger: bool = False) -> None:
        """Render one maintenance row with a label, hint, and an action button."""
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=14, pady=10)

        text_col = ctk.CTkFrame(row, fg_color="transparent")
        text_col.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(text_col, text=label, font=_font(11, "bold"),
                     text_color=C["text"], anchor="w").pack(fill="x")
        ctk.CTkLabel(text_col, text=hint, font=_font(9),
                     text_color=C["text_dim"], anchor="w").pack(fill="x")

        color  = C["error"] if danger else C["accent"]
        ctk.CTkButton(
            row, text="Ejecutar", width=86, height=30,
            font=_font(10, "bold"), fg_color=color,
            hover_color=color, text_color="#000" if not danger else "#FFF",
            corner_radius=6, command=command,
        ).pack(side="right", padx=(8, 0))

    # ── Maintenance handlers ──────────────────────────────────────────────────

    def _confirm(self, title: str, message: str) -> bool:
        """Show a yes/no confirmation dialog.  Returns True if the user confirmed."""
        from tkinter import messagebox
        return messagebox.askyesno(title, message, parent=self.winfo_toplevel())

    def _handle_clear_cache(self) -> None:
        if self._on_clear_cover_cache:
            self._on_clear_cover_cache()

    def _handle_clear_history(self) -> None:
        if self._confirm(
            "Borrar historial",
            "¿Seguro que quieres borrar todo el historial de descargas?\n"
            "Esta acción no se puede deshacer.",
        ) and self._on_clear_history:
            self._on_clear_history()

    def _handle_reset_config(self) -> None:
        if self._confirm(
            "Restablecer ajustes",
            "Volver a los valores por defecto.\n"
            "Tus credenciales de API se conservarán.\n\n"
            "¿Continuar?",
        ) and self._on_reset_config:
            self._on_reset_config()

    # ── Theme ─────────────────────────────────────────────────────────────────

    def _select_theme(self, name: str) -> None:
        self._theme_var.set(name)
        for btn in self._theme_grid.winfo_children():
            n      = getattr(btn, "_theme_name", "")
            accent = getattr(btn, "_theme_accent", C["accent"])
            btn.configure(border_color=accent if n == name else C["border"])
        if self._on_theme_change:
            self._on_theme_change(name)

    def _card(self, parent) -> ctk.CTkFrame:
        f = ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=10)
        f.pack(fill="x", pady=(0, 6))
        return f

    def _field_lbl(self, parent, text: str) -> None:
        ctk.CTkLabel(parent, text=text, font=_font(10),
                     text_color=C["text_mid"]).pack(anchor="w", padx=14, pady=(12, 4))

    def _browse(self) -> None:
        folder = filedialog.askdirectory()
        if folder:
            self._folder_var.set(folder)

    def _save(self) -> None:
        try:
            threads = max(1, min(int(self._threads_var.get()), 4))
        except ValueError:
            threads = 2

        cfg = {
            "theme":                   self._theme_var.get(),
            "download_folder":         self._folder_var.get(),
            "preferred_format":        self._fmt_var.get(),
            "preferred_quality":       self._qual_var.get(),
            "folder_structure":        self._struct_var.get(),
            "auto_fix_metadata":       self._auto_fix_var.get(),
            "subfolder_per_platform":  self._subfolder_var.get(),
            "threads":                 threads,
            "notify_on_complete":      self._notify_var.get(),
            "open_folder_on_complete": self._open_folder_var.get(),
            "sound_on_complete":       self._sound_var.get(),
            "spotify":    {"client_id": self._sp_id_var.get(),
                           "client_secret": self._sp_secret_var.get()},
            "soundcloud": {"client_id": self._sc_id_var.get()},
        }
        self._ctrl.save_config(cfg)

        # Apply runtime-reconfigurable settings immediately.
        self._ctrl.update_thread_count(threads)

        sp_id, sp_secret = self._sp_id_var.get(), self._sp_secret_var.get()
        if sp_id and sp_secret:
            self._ctrl.update_spotify_credentials(sp_id, sp_secret)
        sc_id = self._sc_id_var.get()
        if sc_id:
            self._ctrl.update_soundcloud_client_id(sc_id)

        self._save_btn.configure(fg_color=C["success"], text="✓  Guardado")
        self.after(1800, lambda: self._save_btn.configure(
            fg_color=C["accent"], text="Guardar configuración"))

        if self._on_save:
            self._on_save()


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────────────────────────────────────

class _NavItem(ctk.CTkFrame):
    def __init__(self, parent, icon: str, label: str, on_click: Callable, **kw):
        super().__init__(parent, fg_color="transparent", corner_radius=8, height=44, **kw)
        self.pack_propagate(False)
        self._on_click = on_click

        self._bar = ctk.CTkFrame(self, width=3, fg_color="transparent", corner_radius=2)
        self._bar.pack(side="left", fill="y", padx=(5, 0), pady=6)

        self._btn = ctk.CTkButton(
            self, text=f"  {icon}   {label}", anchor="w",
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text_dim"], font=_font(10, "bold"),
            height=38, corner_radius=6, command=self._on_click)
        self._btn.pack(side="left", fill="x", expand=True, padx=(2, 8), pady=3)

        self._badge = ctk.CTkLabel(
            self, text="", font=_font(8, "bold"),
            fg_color=C["accent"], text_color="#000",
            corner_radius=6, width=20, height=16)

    def set_active(self, active: bool) -> None:
        if active:
            self._bar.configure(fg_color=C["accent"])
            self._btn.configure(fg_color=C["surface"], text_color=C["accent"])
        else:
            self._bar.configure(fg_color="transparent")
            self._btn.configure(fg_color="transparent", text_color=C["text_mid"])

    def set_badge(self, count: int) -> None:
        if count > 0:
            self._badge.configure(text=str(count))
            self._badge.place(relx=0.80, rely=0.18)
        else:
            self._badge.place_forget()


class Sidebar(ctk.CTkFrame):
    _ITEMS = [
        ("dashboard", "◈", "DASHBOARD"),
        ("search",    "🔍", "BUSCAR"),
        ("downloads", "↓",  "DESCARGAS"),
        ("history",   "≡",  "HISTORIAL"),
        ("settings",  "⚙",  "AJUSTES"),
    ]

    def __init__(self, parent, on_navigate: Callable, **kw):
        super().__init__(parent, width=196, fg_color=C["sidebar"],
                         corner_radius=0, **kw)
        self.pack_propagate(False)
        self._on_navigate = on_navigate
        self._active = ""
        self._items: Dict[str, _NavItem] = {}
        self._build()

    def _build(self) -> None:
        brand = ctk.CTkFrame(self, fg_color="transparent", height=72)
        brand.pack(fill="x")
        brand.pack_propagate(False)
        ctk.CTkLabel(brand, text=__app_name__.upper(), font=_font(17, "bold"),
                     text_color=C["accent"]).pack(anchor="w", padx=20, pady=(22, 0))
        ctk.CTkLabel(brand, text=__app_subtitle__.upper(), font=_font(7, "bold"),
                     text_color=C["text_dim"]).pack(anchor="w", padx=20)

        Divider(self).pack(fill="x", pady=(8, 12), padx=14)

        for tab_id, icon, label in self._ITEMS:
            item = _NavItem(self, icon=icon, label=label,
                            on_click=lambda t=tab_id: self._navigate(t))
            item.pack(fill="x", padx=8, pady=2)
            self._items[tab_id] = item

        Divider(self).pack(side="bottom", fill="x", padx=14, pady=(0, 8))
        ctk.CTkLabel(self, text=f"v{__version__}  ·  yt-dlp", font=_font(8),
                     text_color=C["text_dim"]).pack(side="bottom", pady=(0, 4))

        self._active = "dashboard"
        if "dashboard" in self._items:
            self._items["dashboard"].set_active(True)

    def _navigate(self, tab_id: str) -> None:
        if self._active and self._active in self._items:
            self._items[self._active].set_active(False)
        self._active = tab_id
        if tab_id in self._items:
            self._items[tab_id].set_active(True)
        self._on_navigate(tab_id)

    def navigate(self, tab_id: str) -> None:
        self._navigate(tab_id)

    def set_download_badge(self, count: int) -> None:
        if "downloads" in self._items:
            self._items["downloads"].set_badge(count)

    def refresh_theme(self) -> None:
        """Update sidebar colours after a theme change."""
        self.configure(fg_color=C["sidebar"])
        for tab_id, item in self._items.items():
            item.set_active(tab_id == self._active)


# ─────────────────────────────────────────────────────────────────────────────
# Main application window
# ─────────────────────────────────────────────────────────────────────────────

class DjTracksDwCrackApp:
    APP_TITLE    = "DJ Tracks  ·  Music Downloader"
    APP_GEOMETRY = "1280x800"
    APP_MIN_SIZE = (960, 640)

    _TAB_TITLES = {
        "dashboard": "DASHBOARD",
        "search":    "BUSCAR",
        "downloads": "DESCARGAS",
        "history":   "HISTORIAL",
        "settings":  "AJUSTES",
    }

    def __init__(self, controller: AppController) -> None:
        self._ctrl    = controller
        self._history = HistoryManager()

        saved_theme = controller.get_config("theme", "Dark Pro")
        apply_theme(saved_theme)

        self._root = ctk.CTk()
        self._root.title(self.APP_TITLE)
        self._root.geometry(self.APP_GEOMETRY)
        self._root.minsize(*self.APP_MIN_SIZE)
        self._root.configure(fg_color=C["bg"])

        self._panels: Dict[str, ctk.CTkFrame] = {}
        self._content_area: Optional[ctk.CTkFrame] = None

        self._set_icon()
        self._build()

        # Register the UI callback via the public setter.
        self._ctrl.set_on_task_update(self._download_panel.on_task_update)

        # Resume any tasks that were pending when the app last closed.
        restored = self._ctrl.resume_restored_queue()
        if restored:
            self._toast(f"Reanudando {len(restored)} descarga{'s' if len(restored) != 1 else ''} pendiente{'s' if len(restored) != 1 else ''}", "info")

    def _set_icon(self) -> None:
        try:
            ico = bundled_resource("assets/icon.ico")
            png = bundled_resource("assets/logo.png")
            if ico.exists():
                self._root.iconbitmap(str(ico))
            elif png.exists():
                self._icon_ref = PhotoImage(file=str(png))
                self._root.iconphoto(True, self._icon_ref)
        except Exception:
            pass

    def _build(self) -> None:
        """Build the full UI skeleton (sidebar + topbar + content area)."""
        outer = ctk.CTkFrame(self._root, fg_color="transparent", corner_radius=0)
        outer.pack(fill="both", expand=True)

        self._sidebar = Sidebar(outer, on_navigate=self._switch_tab)
        self._sidebar.pack(side="left", fill="y")

        self._sidebar_border = ctk.CTkFrame(
            outer, width=1, fg_color=C["border"], corner_radius=0)
        self._sidebar_border.pack(side="left", fill="y")

        right = ctk.CTkFrame(outer, fg_color="transparent", corner_radius=0)
        right.pack(side="left", fill="both", expand=True)

        # Topbar
        self._topbar = ctk.CTkFrame(right, height=50, fg_color=C["panel"], corner_radius=0)
        self._topbar.pack(fill="x")
        self._topbar.pack_propagate(False)
        self._topbar_title = ctk.CTkLabel(
            self._topbar, text="DASHBOARD",
            font=_font(11, "bold"), text_color=C["text_mid"])
        self._topbar_title.pack(side="left", padx=22)

        ctk.CTkLabel(self._topbar,
                     text="Ctrl+F  Buscar   Ctrl+D  Descargas   Ctrl+H  Historial",
                     font=_font(8), text_color=C["text_dim"]).pack(side="right", padx=16)

        self._topbar_border = ctk.CTkFrame(right, height=1, fg_color=C["border"], corner_radius=0)
        self._topbar_border.pack(fill="x")

        self._content_area = ctk.CTkFrame(right, fg_color="transparent", corner_radius=0)
        self._content_area.pack(fill="both", expand=True)

        self._build_panels()

        # Status bar
        self._statusbar = ctk.CTkFrame(self._root, height=22, fg_color=C["sidebar"], corner_radius=0)
        self._statusbar.pack(side="bottom", fill="x")
        self._statusbar.pack_propagate(False)
        ctk.CTkLabel(self._statusbar,
                     text="DJ Tracks  ·  yt-dlp  ·  Spotify  ·  Apple Music  ·  SoundCloud",
                     font=_font(8), text_color=C["text_dim"]).pack(side="left", padx=12)
        self._status_lbl = ctk.CTkLabel(self._statusbar, text="", font=_font(8))
        self._status_lbl.pack(side="right", padx=12)
        self.refresh_status()

        self._show_panel("dashboard")
        self._bind_shortcuts()

    def _build_panels(self) -> None:
        """Create (or recreate) all content panels inside the content area."""
        self._dashboard_panel = DashboardPanel(self._content_area, history=self._history)
        self._search_panel    = SearchPanel(
            self._content_area, self._ctrl, on_add_track=self._on_add_track)
        self._download_panel  = DownloadPanel(
            self._content_area, self._ctrl, self._history,
            on_count_change=self._on_count_change,
            on_task_complete=self._on_task_complete)
        self._history_panel   = HistoryPanel(
            self._content_area, history=self._history,
            on_dashboard_refresh=lambda: self._dashboard_panel.refresh())
        self._settings_panel  = SettingsPanel(
            self._content_area, self._ctrl,
            on_save              = self._on_settings_saved,
            on_theme_change      = self._on_theme_selected,
            on_clear_history     = self._on_clear_history,
            on_clear_cover_cache = self._on_clear_cover_cache,
            on_reset_config      = self._on_reset_config)

        self._panels = {
            "dashboard": self._dashboard_panel,
            "search":    self._search_panel,
            "downloads": self._download_panel,
            "history":   self._history_panel,
            "settings":  self._settings_panel,
        }

    def _bind_shortcuts(self) -> None:
        """Register all global keyboard shortcuts."""
        binds = {
            "<Control-f>": lambda _: self._focus_search(),
            "<Control-F>": lambda _: self._focus_search(),
            "<Control-d>": lambda _: self._sidebar.navigate("downloads"),
            "<Control-D>": lambda _: self._sidebar.navigate("downloads"),
            "<Control-h>": lambda _: self._sidebar.navigate("history"),
            "<Control-H>": lambda _: self._sidebar.navigate("history"),
            "<Control-q>": lambda _: self._quit(),
            "<Control-Q>": lambda _: self._quit(),
        }
        for key, cb in binds.items():
            self._root.bind_all(key, cb)

    # ── Navigation ─────────────────────────────────────────────────────────────

    def _switch_tab(self, tab: str) -> None:
        self._show_panel(tab)
        if tab == "history":
            self._history_panel.refresh()
        elif tab == "dashboard":
            self._dashboard_panel.refresh()

    def _show_panel(self, tab: str) -> None:
        for p in self._panels.values():
            p.pack_forget()
        self._panels[tab].pack(fill="both", expand=True)
        self._topbar_title.configure(text=self._TAB_TITLES.get(tab, tab.upper()))

    def _focus_search(self) -> None:
        self._sidebar.navigate("search")
        self._show_panel("search")
        self._search_panel.focus_search()

    # ── Callbacks ──────────────────────────────────────────────────────────────

    def _on_count_change(self, active: int) -> None:
        self._sidebar.set_download_badge(active)
        self._dashboard_panel.update_queue_count(active)
        if active:
            self._root.title(f"DJ Tracks  ·  {active} descargando…")
        else:
            self._root.title(self.APP_TITLE)

    def _on_add_track(self, track: TrackInfo) -> None:
        self._ctrl.add_to_queue(track)
        name = f"{track.artist_str} — {track.title}"
        self._toast(f"Añadido: {name[:60]}")

    # ── Task completion side-effects (toggleable from Settings) ───────────────

    def _on_task_complete(self, task: DownloadTask) -> None:
        """Dispatch optional per-completion actions according to user prefs."""
        if self._ctrl.get_config("notify_on_complete", True):
            name = f"{task.track.artist_str} — {task.track.title}"
            self._toast(f"✓ Listo: {name[:55]}", "success")

        if self._ctrl.get_config("open_folder_on_complete", False) and task.output_path:
            _open_in_file_manager(task.output_path.parent)

        if self._ctrl.get_config("sound_on_complete", False):
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_OK)
            except Exception:
                # Non-Windows or sound system unavailable — silently ignore.
                pass

    # ── Maintenance handlers (wired from SettingsPanel) ───────────────────────

    def _on_clear_history(self) -> None:
        self._history.clear()
        self._dashboard_panel.refresh()
        self._history_panel.refresh()
        self._toast("Historial borrado", "success")

    def _on_clear_cover_cache(self) -> None:
        n = _COVER_CACHE.size()
        _COVER_CACHE.clear()
        if n:
            self._toast(f"Caché vaciada — {n} imágen{'es' if n != 1 else ''} liberadas", "success")
        else:
            self._toast("La caché ya estaba vacía", "info")

    def _on_reset_config(self) -> None:
        self._ctrl.reset_config()
        # Rebuild settings panel so the inputs reflect the reset state.
        self._settings_panel.destroy()
        self._settings_panel = SettingsPanel(
            self._content_area, self._ctrl,
            on_save              = self._on_settings_saved,
            on_theme_change      = self._on_theme_selected,
            on_clear_history     = self._on_clear_history,
            on_clear_cover_cache = self._on_clear_cover_cache,
            on_reset_config      = self._on_reset_config)
        self._panels["settings"] = self._settings_panel
        self._show_panel("settings")
        self.refresh_status()
        self._toast("Ajustes restablecidos", "success")

    def _on_settings_saved(self) -> None:
        self._toast("Configuración guardada.", "success")
        self.refresh_status()

    def _on_theme_selected(self, name: str) -> None:
        """Save theme immediately, then schedule panel rebuild on next event loop tick."""
        self._ctrl.save_config({"theme": name})
        self._root.after(0, lambda: self._apply_theme(name))

    def _apply_theme(self, name: str) -> None:
        """Rebuild all content panels with the new colour palette."""
        apply_theme(name)
        active_tab = self._sidebar._active

        # Temporarily clear the callback to avoid calls to the destroyed panel.
        self._ctrl.set_on_task_update(None)

        for panel in self._panels.values():
            panel.destroy()

        # Update static containers.
        self._root.configure(fg_color=C["bg"])
        self._topbar.configure(fg_color=C["panel"])
        self._topbar_border.configure(fg_color=C["border"])
        self._sidebar_border.configure(fg_color=C["border"])
        self._statusbar.configure(fg_color=C["sidebar"])

        self._build_panels()

        # Re-register callback and repopulate in-progress downloads.
        self._ctrl.set_on_task_update(self._download_panel.on_task_update)
        self._download_panel.populate_from_existing(self._ctrl.queue)

        self._sidebar.refresh_theme()
        self._show_panel(active_tab)
        self.refresh_status()
        self._toast(f"Tema: {name}", "info")

    def refresh_status(self) -> None:
        """Refresh the bottom-bar service status label."""
        diag  = self._ctrl.search_diagnostics()
        text  = "  ·  ".join(diag) if diag else "Todos los servicios listos"
        color = C["warning"] if diag else C["success"]
        self._status_lbl.configure(text=text, text_color=color)

    def _toast(self, message: str, kind: str = "info") -> None:
        Toast(self._root, message, kind=kind)

    def _quit(self) -> None:
        self._ctrl.shutdown()
        self._root.quit()

    def run(self) -> None:
        """Start the Tkinter main loop."""
        self._root.protocol("WM_DELETE_WINDOW", self._quit)
        self._root.mainloop()
