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
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500", "bc": "#629AA9",
        "done_tint": "#0D1F18", "error_tint": "#1F0D12",
    },
    "Neon Blue": {
        "bg": "#020208", "sidebar": "#040412", "panel": "#060618",
        "card": "#0A0A20", "card_hover": "#10103A", "surface": "#080820",
        "border": "#0F1045", "border_focus": "#1530B0",
        "accent": "#1E90FF", "accent_dim": "#0055CC", "accent2": "#00DDCC",
        "text": "#D0E8FF", "text_mid": "#5878AA", "text_dim": "#2C4060",
        "success": "#00FF99", "error": "#FF3366", "warning": "#FFCC00",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500", "bc": "#629AA9",
        "done_tint": "#0A2018", "error_tint": "#200810",
    },
    "Neon Purple": {
        "bg": "#06020C", "sidebar": "#0A0418", "panel": "#0C0620",
        "card": "#130828", "card_hover": "#1C1038", "surface": "#10061C",
        "border": "#220838", "border_focus": "#5515A8",
        "accent": "#A020FF", "accent_dim": "#6010CC", "accent2": "#FF20AA",
        "text": "#EED0FF", "text_mid": "#7848AA", "text_dim": "#4C2C66",
        "success": "#20FF80", "error": "#FF2050", "warning": "#FFAA20",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500", "bc": "#629AA9",
        "done_tint": "#0A1C12", "error_tint": "#1C060C",
    },
    "Carbon Black": {
        "bg": "#080808", "sidebar": "#0E0E0E", "panel": "#121212",
        "card": "#1A1A1A", "card_hover": "#222222", "surface": "#161616",
        "border": "#2A2A2A", "border_focus": "#444444",
        "accent": "#FF6B00", "accent_dim": "#CC5500", "accent2": "#FFB800",
        "text": "#F0EEE8", "text_mid": "#888880", "text_dim": "#505048",
        "success": "#00CC66", "error": "#FF3333", "warning": "#FFCC00",
        "spotify": "#1DB954", "apple": "#FC3C44", "sc": "#FF5500", "bc": "#629AA9",
        "done_tint": "#0C1A10", "error_tint": "#1A0808",
    },
}

# Active theme palette — updated by apply_theme().
C: Dict[str, str] = dict(THEMES["Dark Pro"])

PLATFORM_COLORS: Dict[str, str] = {}
PLATFORM_LABELS: Dict[str, str] = {
    "spotify":    "SPOTIFY",
    "applemusic": "APPLE MUSIC",
    "soundcloud": "SOUNDCLOUD",
    "bandcamp":   "BANDCAMP",
    "youtube":    "YOUTUBE",
}


def apply_theme(name: str) -> None:
    """Update the global C palette and platform colour refs from a named theme."""
    global C, PLATFORM_COLORS
    t = THEMES.get(name, THEMES["Dark Pro"])
    C.update(t)
    PLATFORM_COLORS.update({
        "spotify":    C["spotify"],
        "applemusic": C["apple"],
        "soundcloud": C["sc"],
        "bandcamp":   C["bc"],
        "youtube":    C.get("yt", "#FF0033"),
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


def _hex_to_rgb(h: str) -> Tuple[int, int, int]:
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))  # type: ignore[return-value]


def _placeholder(size: int) -> ctk.CTkImage:
    """A subtle, theme-aware cover placeholder with a centred music glyph."""
    from PIL import ImageDraw

    # Soft vertical gradient from surface → card so it reads as a "frame"
    # rather than a flat block while the real artwork loads.
    top    = _hex_to_rgb(C["surface"])
    bottom = _hex_to_rgb(C["card"])
    img    = Image.new("RGB", (size, size), bottom)
    draw   = ImageDraw.Draw(img)
    for y in range(size):
        t = y / max(1, size - 1)
        draw.line(
            [(0, y), (size, y)],
            fill=(
                int(top[0] + (bottom[0] - top[0]) * t),
                int(top[1] + (bottom[1] - top[1]) * t),
                int(top[2] + (bottom[2] - top[2]) * t),
            ),
        )

    # Centred ♪ glyph, sized to the cover. Try a TrueType font for crisp
    # scaling; fall back to a drawn circle if no font is available.
    glyph_color = _hex_to_rgb(C["text_dim"])
    try:
        from PIL import ImageFont
        fs   = max(12, int(size * 0.42))
        font = None
        for name in ("seguisym.ttf", "segoeui.ttf", "arial.ttf", "DejaVuSans.ttf"):
            try:
                font = ImageFont.truetype(name, fs)
                break
            except Exception:
                continue
        if font is not None:
            box = draw.textbbox((0, 0), "♪", font=font)
            tw, th = box[2] - box[0], box[3] - box[1]
            draw.text(((size - tw) / 2 - box[0], (size - th) / 2 - box[1]),
                      "♪", fill=glyph_color, font=font)
        else:
            raise RuntimeError("no font")
    except Exception:
        r = max(6, size // 6)
        cx = cy = size // 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=glyph_color, width=max(1, size // 60))

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
    _W   = 360
    _H   = 56
    _GAP = 10                      # vertical gap between stacked toasts
    _ICON = {"info": "ℹ", "success": "✓", "error": "✕"}

    # Class-level registry of live toasts so multiple notifications stack
    # instead of overlapping in the same corner.
    _active: List["Toast"] = []

    def __init__(self, root: ctk.CTk, message: str, kind: str = "info", ms: int = 2800):
        accent = {"info": C["accent"], "success": C["success"], "error": C["error"]}.get(kind, C["accent"])
        # Use a theme surface colour so the toast matches all four themes.
        super().__init__(root, fg_color=C["card"], corner_radius=10,
                         border_width=1, border_color=accent,
                         width=self._W, height=self._H)
        self.pack_propagate(False)
        self.grid_propagate(False)
        # NOTE: do NOT name this `_root` — that shadows tkinter's Misc._root()
        # method and breaks the whole widget tree ('CTk' object is not callable).
        self._owner = root

        # Left accent strip.
        ctk.CTkFrame(self, width=4, fg_color=accent, corner_radius=0).place(
            x=0, y=0, relheight=1)

        # Icon badge.
        ctk.CTkLabel(self, text=self._ICON.get(kind, "ℹ"), font=_font(15, "bold"),
                     text_color=accent, width=26).pack(side="left", padx=(14, 0))

        ctk.CTkLabel(self, text=message, text_color=C["text"], font=_font(12),
                     wraplength=290, justify="left", anchor="w").pack(
                         side="left", fill="both", expand=True, padx=(6, 14), pady=10)

        Toast._active.append(self)
        self._reposition_all()

        # Slide-in: start a few px to the right, glide to rest.
        self._target_x = max(0, root.winfo_width() - self._W - 16)
        self._animate_in(self._target_x + 24)

        root.after(ms, self._safe_destroy)

    def _animate_in(self, start_x: int) -> None:
        target = self._target_x
        x = start_x

        def _step() -> None:
            nonlocal x
            if not self.winfo_exists():
                return
            x += (target - x) * 0.35
            if abs(target - x) < 1:
                x = target
            cur_y = self.winfo_y()
            self.place(x=int(x), y=cur_y)
            if x != target:
                self.after(16, _step)

        _step()

    @classmethod
    def _reposition_all(cls) -> None:
        """Stack all live toasts bottom-up in the lower-right corner."""
        live = [t for t in cls._active if t.winfo_exists()]
        cls._active = live
        if not live:
            return
        root = live[0]._owner
        root.update_idletasks()
        rh = root.winfo_height()
        rw = root.winfo_width()
        x  = max(0, rw - cls._W - 16)
        y  = rh - cls._H - 16
        for t in reversed(live):                      # newest at the bottom
            t._target_x = x
            t.place(x=x, y=max(0, y))
            y -= (cls._H + cls._GAP)

    def _safe_destroy(self) -> None:
        try:
            if self in Toast._active:
                Toast._active.remove(self)
            self.destroy()
            Toast._reposition_all()
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
    """Horizontal list row for search results.  Supports a multi-select
    checkbox and a distinct look for whole-album results."""

    def __init__(self, parent, track: TrackInfo, on_add: Callable,
                 on_toggle: Optional[Callable] = None, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=6, **kw)
        self._track   = track
        self._on_add  = on_add
        self._on_toggle = on_toggle
        self._added   = False
        self._sel_var = ctk.BooleanVar(value=False)
        self._build()
        self.bind("<Enter>", lambda _: self.configure(fg_color=C["card_hover"]) if not self._added else None)
        self.bind("<Leave>", lambda _: self.configure(fg_color=C["card"])       if not self._added else None)
        self.bind("<Button-3>", lambda e, t=track: self._show_track_menu(e, t))

    @property
    def selected(self) -> bool:
        return self._sel_var.get()

    @property
    def track(self) -> TrackInfo:
        return self._track

    def _build(self) -> None:
        t  = self._track
        is_album = getattr(t, "is_album", False)
        pc = PLATFORM_COLORS.get(t.platform, C["text_dim"])

        ctk.CTkFrame(self, width=3, fg_color=pc, corner_radius=0).pack(side="left", fill="y")

        # Multi-select checkbox.
        chk = ctk.CTkCheckBox(self, text="", width=24, variable=self._sel_var,
                              checkbox_width=18, checkbox_height=18,
                              fg_color=C["accent"], hover_color=C["accent_dim"],
                              border_color=C["border_focus"], corner_radius=4,
                              command=self._toggle)
        chk.pack(side="left", padx=(8, 0))

        self._cover = ctk.CTkLabel(self, text="", width=56, height=56)
        self._cover.pack(side="left", padx=(8, 12), pady=10)
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
        title_text = (f"💿  {t.title}" if is_album else (t.title or "Unknown"))
        ctk.CTkLabel(top, text=title_text, font=_font(13, "bold"),
                     text_color=C["text"], anchor="w").pack(side="left")
        if t.year:
            ctk.CTkLabel(top, text=f"  {t.year}", font=_font(10),
                         text_color=C["text_dim"]).pack(side="left")

        ctk.CTkLabel(info, text=t.artist_str or "Unknown", font=_font(11),
                     text_color=C["text_mid"], anchor="w").pack(fill="x")

        bot = ctk.CTkFrame(info, fg_color="transparent")
        bot.pack(fill="x", pady=(3, 0))
        if is_album:
            cnt = f"ÁLBUM · {t.track_count} pistas" if t.track_count else "ÁLBUM"
            ctk.CTkLabel(bot, text=cnt, font=_font(9, "bold"),
                         text_color=C["warning"], anchor="w").pack(side="left")
        elif t.album:
            ctk.CTkLabel(bot, text=t.album, font=_font(10),
                         text_color=C["text_dim"], anchor="w").pack(side="left")
        if not is_album:
            ctk.CTkLabel(bot, text=t.duration_str, font=_font(10, mono=True),
                         text_color=C["text_dim"]).pack(side="right")

    def _toggle(self) -> None:
        if self._on_toggle:
            self._on_toggle(self)

    def _add(self) -> None:
        if self._added:
            return
        self._added = True
        self._btn.configure(text="✓", fg_color=C["success"], state="disabled")
        self.configure(fg_color=C["done_tint"])
        self._on_add(self._track)

    def flash(self) -> None:
        self.configure(fg_color=C["card_hover"])
        self.after(200, lambda: self.configure(
            fg_color=C["done_tint"] if self._added else C["card"]))


class TrackCard(ctk.CTkFrame, _TrackContextMenuMixin):
    """Grid card for search results."""

    _CARD_W = 185
    _CARD_H = 275

    def __init__(self, parent, track: TrackInfo, on_add: Callable,
                 on_toggle: Optional[Callable] = None, **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=8,
                         width=self._CARD_W, height=self._CARD_H,
                         border_width=1, border_color=C["card"], **kw)
        self.grid_propagate(False)
        self._track   = track
        self._on_add  = on_add
        self._on_toggle = on_toggle
        self._added   = False
        self._sel_var = ctk.BooleanVar(value=False)
        self._build()
        self.bind("<Button-3>", lambda e, t=track: self._show_track_menu(e, t))
        # Hover: lift the card with a coloured border + subtle bg change.
        # Bind on the card and every non-interactive child so movement across
        # children doesn't flicker; <Leave> re-checks the real pointer bounds.
        self._hover_targets = [self]
        self._bind_hover(self)

    def _bind_hover(self, widget) -> None:
        widget.bind("<Enter>", self._on_hover_enter, add="+")
        widget.bind("<Leave>", self._on_hover_leave, add="+")
        for child in widget.winfo_children():
            if child is getattr(self, "_btn", None):
                continue
            self._bind_hover(child)

    def _on_hover_enter(self, _event=None) -> None:
        if self._added:
            return
        pc = PLATFORM_COLORS.get(self._track.platform, C["accent"])
        self.configure(fg_color=C["card_hover"], border_color=pc)

    def _on_hover_leave(self, _event=None) -> None:
        if self._added:
            return
        # Only revert when the pointer has actually left the card's bounds —
        # avoids flicker when moving between the card's own child widgets.
        try:
            px, py = self.winfo_pointerxy()
            x0, y0 = self.winfo_rootx(), self.winfo_rooty()
            x1, y1 = x0 + self.winfo_width(), y0 + self.winfo_height()
            if x0 <= px < x1 and y0 <= py < y1:
                return
        except Exception:
            pass
        self.configure(fg_color=C["card"], border_color=C["card"])

    def _build(self) -> None:
        t  = self._track
        is_album = getattr(t, "is_album", False)
        pc = PLATFORM_COLORS.get(t.platform, C["text_dim"])

        head = ctk.CTkFrame(self, height=3, fg_color=pc, corner_radius=0)
        head.pack(fill="x")

        # Multi-select checkbox overlaid top-left.
        self._chk = ctk.CTkCheckBox(self, text="", width=22, variable=self._sel_var,
                                    checkbox_width=18, checkbox_height=18,
                                    fg_color=C["accent"], hover_color=C["accent_dim"],
                                    border_color=C["border_focus"], corner_radius=4,
                                    command=self._toggle)
        self._chk.place(x=8, y=8)

        self._cover = ctk.CTkLabel(self, text="", width=155, height=155)
        self._cover.pack(padx=15, pady=(10, 6))
        _load_cover_async(self, self._cover, t.cover_url, 155)

        title_text = (f"💿 {t.title}" if is_album else (t.title or "Unknown"))
        ctk.CTkLabel(self, text=title_text, font=_font(12, "bold"),
                     text_color=C["text"], anchor="w", wraplength=161,
                     justify="left").pack(fill="x", padx=12)

        if is_album:
            sub = f"{t.artist_str or '—'}  ·  " + (
                f"{t.track_count} pistas" if t.track_count else "álbum")
            sub_color = C["warning"]
        else:
            sub = f"{t.artist_str or '—'}" + (f"  ·  {t.year}" if t.year else "")
            sub_color = C["text_mid"]
        ctk.CTkLabel(self, text=sub, font=_font(10), text_color=sub_color,
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
        if not is_album:
            ctk.CTkLabel(bot, text=t.duration_str, font=_font(9, mono=True),
                         text_color=C["text_dim"]).pack(side="right", padx=(0, 6))

    def _toggle(self) -> None:
        if self._on_toggle:
            self._on_toggle(self)

    @property
    def selected(self) -> bool:
        return self._sel_var.get()

    @property
    def track(self) -> TrackInfo:
        return self._track

    def _add(self) -> None:
        if self._added:
            return
        self._added = True
        self._btn.configure(text="✓", fg_color=C["success"], state="disabled")
        # Mark the whole card as added with a success-tinted border.
        self.configure(fg_color=C["done_tint"], border_color=C["success"])
        self._on_add(self._track)

    def flash(self) -> None:
        self.configure(fg_color=C["card_hover"])
        self.after(200, lambda: self.configure(
            fg_color=C["done_tint"] if self._added else C["card"]))


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
    - Right-click  → context menu (open file, open folder, copy path, redownload).
    - ↻ button     → re-downloads the track (handy after errors or to refresh).
    - ✕ button     → removes this record from the history.
    """

    def __init__(self, parent, record,
                 on_delete:     Optional[Callable] = None,
                 on_redownload: Optional[Callable] = None,
                 queue_paths:   Optional[list]     = None,
                 **kw):
        super().__init__(parent, fg_color=C["card"], corner_radius=5, **kw)
        self._record        = record
        self._on_delete     = on_delete
        self._on_redownload = on_redownload
        self._queue_paths   = queue_paths or []
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

        # Title row: title + (optional) Beatport / DB / local badge inline.
        title_row = ctk.CTkFrame(info, fg_color="transparent")
        title_row.pack(fill="x")
        ctk.CTkLabel(title_row, text=r.title or "Unknown",
                     font=_font(11, "bold"),
                     text_color=C["text"], anchor="w").pack(side="left")
        src = getattr(r, "metadata_source", "") or ""
        if src:
            badge_styles = {
                "beatport":   ("BEATPORT", "#00FFB9", "#003B2A"),
                "getsongbpm": ("DB",       C["text_mid"], C["surface"]),
                "librosa":    ("LOCAL",    C["text_dim"], C["surface"]),
            }
            label, fg, bg = badge_styles.get(src, (src.upper(), C["text_dim"], C["surface"]))
            badge_w = max(36, len(label) * 7 + 12)
            ctk.CTkLabel(title_row, text=label,
                         font=_font(7, "bold"),
                         text_color=fg, fg_color=bg,
                         corner_radius=4,
                         width=badge_w, height=16
                         ).pack(side="left", padx=(8, 0))

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

        # Redownload button — emphasised in red for failed entries, subtle for
        # successful ones (useful for "I want a fresh copy" without errors too).
        rd_color = C["error"] if not ok else C["accent"]
        self._rd_btn = ctk.CTkButton(
            self, text="↻", width=28, height=28, font=_font(13, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=rd_color, corner_radius=5,
            command=self._handle_redownload,
        )
        self._rd_btn.pack(side="right", padx=(0, 2))

        # Play / pause button — only shown when the file actually exists on
        # disk (failed downloads have a record but no path).
        self._has_file = bool(r.path) and Path(r.path).exists() if r.path else False
        self._pl_btn = ctk.CTkButton(
            self, text="▶", width=28, height=28, font=_font(12, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["accent"] if self._has_file else C["text_dim"],
            corner_radius=5,
            command=self._handle_play,
            state="normal" if self._has_file else "disabled",
        )
        self._pl_btn.pack(side="right", padx=(0, 2))
        # Subscribe to player state changes so the button icon stays in sync.
        if self._has_file:
            from utils.audio_player import AudioPlayer
            AudioPlayer.get().subscribe(self._refresh_play_btn)

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
        # but skip the action buttons (they have their own commands).
        skips = {self._del_btn, self._rd_btn, self._pl_btn}
        self._bind_recursive(self, "<Double-Button-1>", self._open_file, skip=skips)
        self._bind_recursive(self, "<Button-3>",        self._show_menu, skip=skips)
        self._bind_recursive(self, "<Enter>", lambda _: self.configure(fg_color=C["card_hover"]))
        self._bind_recursive(self, "<Leave>", lambda _: self.configure(fg_color=C["card"]))

    def _bind_recursive(self, widget, sequence: str, callback, skip=None) -> None:
        if skip and (widget is skip or (isinstance(skip, set) and widget in skip)):
            return
        widget.bind(sequence, callback)
        for child in widget.winfo_children():
            self._bind_recursive(child, sequence, callback, skip=skip)

    def _handle_delete(self) -> None:
        if self._on_delete:
            self._on_delete(self._record)

    def _handle_redownload(self) -> None:
        if not self._on_redownload:
            return
        # Visual feedback: dim the button while the search/enqueue runs in
        # the background.
        self._rd_btn.configure(state="disabled", text="…")
        self.after(1500, lambda: self._rd_btn.configure(state="normal", text="↻"))
        self._on_redownload(self._record)

    def _handle_play(self) -> None:
        """Toggle play / pause for this row's audio file.

        Pressing play on a new row stops whatever was playing before.
        """
        if not self._has_file:
            return
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        path = Path(self._record.path)
        # Same row toggled twice → pause/resume; new row → load + play.
        if player.current and player.current.resolve() == path.resolve():
            player.toggle_pause()
        else:
            # Wire up the queue so the player bar can do prev/next across
            # the current history page.
            if self._queue_paths:
                player.set_queue([Path(p) for p in self._queue_paths if p],
                                 path)
            player.play(path)

    def _refresh_play_btn(self) -> None:
        """Called by the AudioPlayer on every state change so the icon
        reflects the actual playback state of *this* row."""
        try:
            if not self.winfo_exists() or not self._has_file:
                return
        except Exception:
            return
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        path = Path(self._record.path)
        is_mine = (player.current is not None
                   and player.current.resolve() == path.resolve())
        if is_mine and not player.paused:
            self._pl_btn.configure(text="⏸", text_color=C["success"])
        else:
            self._pl_btn.configure(text="▶", text_color=C["accent"])

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
        menu.add_command(label="↻  Redescargar",
                         command=self._handle_redownload,
                         state="normal" if self._on_redownload else "disabled")
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
            for plat, sym in [("spotify", "Spotify"), ("applemusic", "Apple"),
                               ("soundcloud", "SoundCl."), ("bandcamp", "Bandcamp")]:
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
    _PLATFORMS    = ["auto", "spotify", "applemusic", "soundcloud", "bandcamp"]
    _PLAT_DISPLAY = {
        "auto":       "Todas",
        "spotify":    "Spotify",
        "applemusic": "Apple Music",
        "soundcloud": "SoundCloud",
        "bandcamp":   "Bandcamp",
    }

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
        # Magnifier glyph — signals "type to search" at a glance.
        ctk.CTkLabel(bar, text="🔍", font=_font(14),
                     text_color=C["text_dim"]).pack(side="left", padx=(14, 0))
        self._entry = ctk.CTkEntry(
            bar, textvariable=self._search_var,
            placeholder_text="Escribe un artista o canción  (o pega una URL)…",
            font=_font(12), fg_color="transparent",
            border_width=0, height=46, text_color=C["text"])
        self._entry.pack(side="left", fill="x", expand=True, padx=(8, 0), pady=6)
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

        # Status label + "Select all" checkbox share a single horizontal row.
        _status_row = ctk.CTkFrame(self, fg_color="transparent")
        _status_row.pack(fill="x", padx=20, pady=(8, 0))

        self._status_lbl = ctk.CTkLabel(_status_row, text="", font=_font(10),
                                        text_color=C["text_dim"], anchor="w")
        self._status_lbl.pack(side="left", fill="x", expand=True, padx=(2, 0))

        # Tri-state "Select all" checkbox — hidden until results are loaded.
        self._sel_all_var = tk.BooleanVar(value=False)
        self._sel_all_chk = ctk.CTkCheckBox(
            _status_row, text="Seleccionar todo",
            variable=self._sel_all_var,
            checkbox_width=18, checkbox_height=18,
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color=C["text_mid"], font=_font(10),
            command=self._toggle_select_all)
        # Do NOT pack here — shown only when results exist.

        self._results_frame = ctk.CTkScrollableFrame(
            self, fg_color="transparent",
            scrollbar_button_color=C["border"],
            scrollbar_button_hover_color=C["border_focus"])
        self._results_frame.pack(fill="both", expand=True, padx=20, pady=(4, 0))

        # Bottom selection bar — hidden until a result checkbox is ticked.
        self._sel_bar = ctk.CTkFrame(self, fg_color="transparent")
        self._sel_btn = ctk.CTkButton(
            self._sel_bar, text="⬇  Descargar seleccionados",
            height=40, font=_font(13, "bold"),
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color="#000", corner_radius=8, command=self._download_selected)
        self._sel_btn.pack(fill="x")

        self._empty_lbl = ctk.CTkLabel(
            self._results_frame, text="",
            font=_font(13), text_color=C["text_dim"], justify="center")

        # Initial hint so it's obvious you can search by name, not only by URL.
        self._show_initial_hint()

    def _show_initial_hint(self) -> None:
        """Display a welcoming hint inviting free-text search."""
        self._empty_lbl.configure(
            text="🔍\n\nBusca por nombre de artista o canción\n"
                 "—  o pega un enlace de Spotify · Apple Music · SoundCloud · Bandcamp\n\n"
                 "Ejemplos:   daft punk one more time     ·     bicep glue     ·     fred again")
        self._empty_lbl.pack(expand=True, pady=40)

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
        self._show_initial_hint()
        self._entry.focus()

    def focus_search(self) -> None:
        self._entry.focus()

    def setup_drag_drop(self, root) -> bool:
        """Wire up drag-and-drop: dropping a URL triggers a search."""
        from utils.dnd import setup_text_drop

        def _on_drop(text: str) -> None:
            # tkinterdnd2 returns the drop wrapped in {} when it contains
            # spaces; clean it up first.
            url = text.strip().strip("{}").strip()
            if not url:
                return
            self._search_var.set(url)
            self._do_search()

        return setup_text_drop(root, self._entry, _on_drop)

    def _set_platform(self, plat: str) -> None:
        changed = self._platform_var.get() != plat
        self._platform_var.set(plat)
        for p, btn in self._chip_btns.items():
            color  = PLATFORM_COLORS.get(p, C["accent"]) if p != "auto" else C["accent"]
            active = p == plat
            btn.configure(
                fg_color=color if active else C["surface"],
                text_color="#000" if active else C["text_mid"],
                border_color=color if active else C["border"])

        # Re-run the search immediately when the platform changes, so the
        # filter applies without the user pressing "Buscar" again.  Only for
        # text queries — URL resolution ignores the platform filter anyway.
        if changed and not self._searching:
            query = self._search_var.get().strip()
            if query and not query.startswith(("http://", "https://")):
                self._do_search()

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

    def _platform_unavailable_hint(self, plat: str) -> str:
        """
        If the user-selected single platform is known to be unavailable
        (no credentials, offline provider, etc.), return a one-line hint
        explaining why no results came back.  Returns "" for "auto" and
        for healthy platforms.
        """
        if plat == "auto":
            return ""
        from utils.validators import Platform
        plat_enum = {
            "spotify":    Platform.SPOTIFY,
            "applemusic": Platform.APPLE_MUSIC,
            "soundcloud": Platform.SOUNDCLOUD,
            "bandcamp":   Platform.BANDCAMP,
        }.get(plat)
        if not plat_enum:
            return ""
        provider = self._ctrl.search_manager.provider_for(plat_enum)
        if provider is None:
            return f"Proveedor '{plat}' no registrado"
        if not getattr(provider, "available", True):
            label = self._PLAT_DISPLAY.get(plat, plat)
            if plat == "spotify":
                return f"{label} no disponible — añade Client ID y Secret en Ajustes"
            return f"{label} no disponible en este momento"
        return ""

    def _show_results(self, results: List[TrackInfo]) -> None:
        self._last_results = list(results)
        self._clear_results()
        if not results:
            # When the user explicitly filtered to a single platform and got
            # nothing back, the most useful feedback is whether that platform
            # is actually reachable / configured.
            current_plat = self._platform_var.get()
            specific_hint = self._platform_unavailable_hint(current_plat)
            if specific_hint:
                self._status_lbl.configure(text=specific_hint, text_color=C["warning"])
                self._empty_lbl.configure(
                    text=f"⚠\n\n{specific_hint}\n\nPrueba con 'Todas' o configura "
                         "las credenciales en Ajustes.")
            else:
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
        for plat, sym in [("spotify", "SP"), ("applemusic", "AM"),
                           ("soundcloud", "SC"), ("bandcamp", "BC")]:
            if counts.get(plat, 0):
                parts.append(f"{sym} {counts[plat]}")
        breakdown = "  ·  " + "  ".join(parts) if parts else ""
        n_alb = sum(1 for t in results if getattr(t, "is_album", False))
        alb_txt = f"  ·  💿 {n_alb} álbum{'es' if n_alb != 1 else ''}" if n_alb else ""
        n = len(results)
        self._status_lbl.configure(
            text=f"{n} resultado{'s' if n != 1 else ''}{breakdown}{alb_txt}"
                 "  —  ＋ añadir · ☑ marca varias",
            text_color=C["success"])

        # Show "Select all" checkbox now that we have results.
        self._sel_all_var.set(False)
        self._sel_all_chk.pack(side="right", padx=(0, 2))

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
                    card = TrackCard(self._results_frame, track, on_add=self._add_track,
                                     on_toggle=self._on_toggle)
                    card.grid(row=idx // cols, column=idx % cols, padx=4, pady=4, sticky="n")
                    self._results.append(card)
                else:
                    row = TrackRow(self._results_frame, track, on_add=self._add_track,
                                   on_toggle=self._on_toggle)
                    row.pack(fill="x", pady=(0, 3))
                    self._results.append(row)
            if offset + BATCH < len(results):
                self.after(10, lambda: _render(offset + BATCH))

        _render(0)

    def _on_toggle(self, widget) -> None:
        """Refresh the bottom selection bar and select-all checkbox whenever a checkbox toggles."""
        n = sum(1 for w in self._results if getattr(w, "selected", False))
        if n:
            self._sel_btn.configure(
                text=f"⬇  Descargar seleccionados ({n})",
                fg_color=C["accent"], text_color="#000", state="normal")
            self._sel_bar.pack(fill="x", padx=20, pady=(0, 14))
        else:
            self._sel_bar.pack_forget()
        self._refresh_select_all_state()

    def _toggle_select_all(self) -> None:
        """Select all / deselect all rendered results.

        The checkbox var is already updated by CTk before this command fires,
        so we read it to know the desired state: True → select all, False → deselect all.
        Partial selection (some but not all) maps to unchecked, so clicking from
        partial state selects all remaining items.
        """
        target = self._sel_all_var.get()
        for w in self._results:
            if hasattr(w, "_sel_var"):
                w._sel_var.set(target)
        # Refresh the bottom bar count without touching _sel_all_var again.
        n = sum(1 for w in self._results if getattr(w, "selected", False))
        if n:
            self._sel_btn.configure(
                text=f"⬇  Descargar seleccionados ({n})",
                fg_color=C["accent"], text_color="#000", state="normal")
            self._sel_bar.pack(fill="x", padx=20, pady=(0, 14))
        else:
            self._sel_bar.pack_forget()

    def _refresh_select_all_state(self) -> None:
        """Sync the select-all checkbox to the current per-item selection state.

        Checked  → all items selected.
        Unchecked → zero or partial selection (clicking will select all).
        """
        if not self._results or not hasattr(self, "_sel_all_var"):
            return
        n_total    = len(self._results)
        n_selected = sum(1 for w in self._results if getattr(w, "selected", False))
        self._sel_all_var.set(n_selected == n_total and n_total > 0)

    def _download_selected(self) -> None:
        chosen = [w.track for w in self._results if getattr(w, "selected", False)]
        if not chosen:
            return
        for w in self._results:
            if getattr(w, "selected", False):
                w.flash()
        # Enqueue in the background (albums expand into many tracks).
        threading.Thread(target=lambda: [self._on_add_track(t) for t in chosen],
                         daemon=True).start()
        self._status_lbl.configure(
            text=f"Añadiendo {len(chosen)} selección(es) a la cola…",
            text_color=C["accent"])

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
        if hasattr(self, "_sel_bar"):
            self._sel_bar.pack_forget()
        if hasattr(self, "_sel_all_chk"):
            self._sel_all_chk.pack_forget()


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

        # Pause / Resume toggle — affects every active download.
        self._paused = False
        self._pause_btn = ctk.CTkButton(
            hdr, text="⏸  Pausar", width=110, height=26, font=_font(9, "bold"),
            fg_color=C["warning"], hover_color=C["warning"],
            text_color="#000", corner_radius=5, command=self._toggle_pause)
        self._pause_btn.pack(side="right", padx=(0, 8))

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

    def _toggle_pause(self) -> None:
        """Pause / resume every active download."""
        self._paused = not self._paused
        if self._paused:
            self._ctrl.downloader.pause()
            self._pause_btn.configure(text="▶  Reanudar", fg_color=C["success"], text_color="#000")
        else:
            self._ctrl.downloader.resume()
            self._pause_btn.configure(text="⏸  Pausar", fg_color=C["warning"], text_color="#000")

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
                 on_dashboard_refresh: Optional[Callable] = None,
                 on_redownload:        Optional[Callable] = None, **kw):
        super().__init__(parent, fg_color=C["panel"], corner_radius=0, **kw)
        self._history              = history
        self._on_dashboard_refresh = on_dashboard_refresh
        self._on_redownload        = on_redownload
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
        ctk.CTkOptionMenu(filters, values=["Todas", "Spotify", "Apple Music", "SoundCloud", "Bandcamp"],
                          variable=self._plat_var, fg_color=C["surface"],
                          button_color=C["border"], dropdown_fg_color=C["card"],
                          font=_font(10), text_color=C["text"], width=140, height=32,
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
                      "Apple Music": "applemusic", "SoundCloud": "soundcloud",
                      "Bandcamp": "bandcamp"}
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
            page_paths = [r.path for r in records if r.path]
            for rec in records:
                HistoryRow(self._list, rec,
                           on_delete=self._delete_record,
                           on_redownload=self._on_redownload,
                           queue_paths=page_paths).pack(
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
        self._cross_retry_var   = ctk.BooleanVar(value=self._ctrl.get_config("cross_platform_retry", True))
        self._check_updates_var = ctk.BooleanVar(value=self._ctrl.get_config("check_updates_on_startup", True))
        self._switch_row(dl_card, "Auto-arreglar metadatos",
                         "Corrige título / artista / álbum tras la descarga",
                         self._auto_fix_var)
        self._switch_row(dl_card, "Sub-carpeta por plataforma",
                         "Crea carpetas separadas: Spotify / Apple Music / SoundCloud",
                         self._subfolder_var)
        self._switch_row(dl_card, "Reintentar en otra plataforma",
                         "Si una descarga falla por DRM / restricción, busca la misma canción en otras fuentes y la encola",
                         self._cross_retry_var)
        self._switch_row(dl_card, "Buscar actualizaciones al iniciar",
                         "Consulta GitHub al arrancar y muestra un aviso si hay una versión nueva",
                         self._check_updates_var)

        # Cookies-from-browser: usa la sesión iniciada del usuario para
        # acceder a contenido que la plataforma sirve sólo a usuarios
        # autenticados (resuelve muchos "DRM" de SoundCloud).
        Divider(dl_card).pack(fill="x", padx=14, pady=2)
        cookies_row = ctk.CTkFrame(dl_card, fg_color="transparent")
        cookies_row.pack(fill="x", padx=14, pady=(8, 14))
        ctk.CTkLabel(cookies_row, text="Cookies del navegador",
                     font=_font(11, "bold"), text_color=C["text"]).pack(anchor="w")
        ctk.CTkLabel(cookies_row,
                     text="Usa tu sesión iniciada para acceder a contenido que la "
                          "plataforma sólo sirve a usuarios autenticados (resuelve "
                          "muchos «DRM» de SoundCloud).  Selecciona el navegador "
                          "donde tengas la sesión.",
                     font=_font(9), text_color=C["text_dim"],
                     wraplength=520, justify="left").pack(anchor="w")
        cookies_choices = ["(desactivado)", "chrome", "firefox", "edge",
                            "brave", "opera", "chromium", "vivaldi", "safari"]
        current = self._ctrl.get_config("cookies_browser", "") or "(desactivado)"
        self._cookies_var = ctk.StringVar(value=current)
        ctk.CTkOptionMenu(
            cookies_row, values=cookies_choices, variable=self._cookies_var,
            fg_color=C["surface"], button_color=C["border"],
            button_hover_color=C["border_focus"],
            dropdown_fg_color=C["card"], dropdown_hover_color=C["card_hover"],
            font=_font(11), text_color=C["text"], width=160, height=30,
        ).pack(anchor="w", pady=(6, 0))

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

        self._notify_var        = ctk.BooleanVar(value=self._ctrl.get_config("notify_on_complete", True))
        self._native_notify_var = ctk.BooleanVar(value=self._ctrl.get_config("native_notify_on_complete", False))
        self._open_folder_var   = ctk.BooleanVar(value=self._ctrl.get_config("open_folder_on_complete", False))
        self._sound_var         = ctk.BooleanVar(value=self._ctrl.get_config("sound_on_complete", False))

        self._switch_row(notif_card, "Mostrar aviso al completar",
                         "Burbuja flotante dentro de la aplicación",
                         self._notify_var)
        self._switch_row(notif_card, "Notificación del sistema",
                         "Notificación nativa de Windows / macOS / Linux (visible aunque minimices)",
                         self._native_notify_var)
        self._switch_row(notif_card, "Abrir carpeta al completar",
                         "Lanza el Explorador en la carpeta del archivo",
                         self._open_folder_var)
        self._switch_row(notif_card, "Sonido al completar",
                         "Pitido del sistema cuando termina cada descarga",
                         self._sound_var)

        # ── DJ · Metadatos avanzados ──────────────────────────────────────────
        SectionLabel(scroll, "DJ · Análisis avanzado").pack(anchor="w", pady=(16, 8))
        dj_card = self._card(scroll)

        self._dj_enrich_var   = ctk.BooleanVar(value=self._ctrl.get_config("dj_enrich", False))
        self._dj_local_var    = ctk.BooleanVar(value=self._ctrl.get_config("dj_local_fallback", False))
        self._dj_filename_var  = ctk.BooleanVar(value=self._ctrl.get_config("dj_filename", False))
        self._dj_replaygain_var = ctk.BooleanVar(value=self._ctrl.get_config("dj_replaygain", False))
        self._dj_quality_var   = ctk.BooleanVar(value=self._ctrl.get_config("dj_quality_check", False))
        self._dedup_var        = ctk.BooleanVar(value=self._ctrl.get_config("dedupe_audio_fp", False))

        self._switch_row(dj_card, "Análisis DJ (BPM · Tonalidad · Camelot)",
                         "Escribe BPM, clave musical y código Camelot en cada archivo (mezcla armónica)",
                         self._dj_enrich_var)

        self._field_lbl(dj_card, "GetSongBPM · API Key  (gratis en getsongbpm.com/api)")
        self._dj_key_var = ctk.StringVar(value=self._ctrl.get_config("dj_getsongbpm_key", ""))
        ctk.CTkEntry(dj_card, textvariable=self._dj_key_var,
                     placeholder_text="Opcional — BPM/clave reales de la base de datos",
                     font=_font(11), fg_color=C["surface"],
                     border_color=C["border"], border_width=1,
                     text_color=C["text"], height=34).pack(fill="x", padx=14, pady=(0, 12))

        Divider(dj_card).pack(fill="x", padx=14, pady=2)
        self._switch_row(dj_card, "Análisis local (librosa)",
                         "Si no hay API key o no se encuentra: analiza el audio localmente (más lento, requiere librosa)",
                         self._dj_local_var)
        self._switch_row(dj_card, "Renombrar archivo DJ  [BPM - Camelot]",
                         "Ej.: «Artist - Title [128 - 8A].mp3»",
                         self._dj_filename_var)
        self._switch_row(dj_card, "ReplayGain (normalizar volumen)",
                         "Mide la sonoridad y escribe etiquetas de ganancia para reproducción uniforme",
                         self._dj_replaygain_var)
        self._switch_row(dj_card, "Avisar si la calidad real es baja",
                         "Detecta cuando un «320 kbps» es en realidad un re-encode de baja calidad",
                         self._dj_quality_var)
        self._switch_row(dj_card, "Evitar duplicados (huella acústica)",
                         "Compara cada descarga con tu librería y descarta duplicados aunque tengan otro nombre (requiere ffmpeg con Chromaprint)",
                         self._dedup_var)

        # ── API Credentials ───────────────────────────────────────────────────
        cred_hdr = ctk.CTkFrame(scroll, fg_color="transparent")
        cred_hdr.pack(fill="x", pady=(16, 8))
        SectionLabel(cred_hdr, "Credenciales de API").pack(side="left")
        ctk.CTkButton(
            cred_hdr, text="❓  ¿Cómo configurar Spotify?", height=26,
            font=_font(9, "bold"), fg_color=C["surface"],
            hover_color=C["card_hover"], text_color=C["spotify"],
            corner_radius=5, command=self._handle_show_setup_wizard,
        ).pack(side="right")

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

        self._maint_button(
            maint_card,
            label=f"Buscar actualizaciones de DJ Tracks  ·  v{__version__}",
            hint="Comprueba GitHub y descarga la última versión si hay una más nueva",
            command=self._handle_update_app)
        Divider(maint_card).pack(fill="x", padx=14, pady=2)

        self._maint_button(
            maint_card,
            label="Actualizar yt-dlp",
            hint="Arregla la mayoría de errores 403 / «vídeo no disponible» (YouTube cambia cada 2-3 meses)",
            command=self._handle_update_ytdlp)
        Divider(maint_card).pack(fill="x", padx=14, pady=2)

        cache_n = _COVER_CACHE.size()
        self._maint_button(
            maint_card,
            label=f"Crear acceso directo en el escritorio",
            hint="Acceso rápido a DJ Tracks en tu escritorio (Win/Mac/Linux)",
            command=self._handle_create_shortcut)
        Divider(maint_card).pack(fill="x", padx=14, pady=2)
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

        # ── Apoyar el proyecto ────────────────────────────────────────────────
        SectionLabel(scroll, "Apoya el proyecto").pack(anchor="w", pady=(16, 8))
        donate_card = self._card(scroll)
        self._maint_button(
            donate_card,
            label="♥  Donar criptomoneda",
            hint="Apoya el desarrollo con cualquier moneda — abre un diálogo con las direcciones",
            command=self._handle_donate)

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

    def _handle_update_app(self) -> None:
        """Check GitHub Releases for a newer DJ Tracks build and offer
        to download + install it."""
        from tkinter import messagebox
        from utils import app_updater

        top = self.winfo_toplevel()

        def _show_toast(msg: str, kind: str = "info") -> None:
            try:
                if hasattr(top, "_toast"):
                    top._toast(msg, kind)
            except Exception:
                pass

        def _worker() -> None:
            info = app_updater.check_for_update(__version__)
            self.after(0, lambda: _on_check_done(info))

        def _on_check_done(info: dict) -> None:
            if not info.get("available"):
                latest = info.get("latest") or "?"
                messagebox.showinfo(
                    "DJ Tracks",
                    f"Ya tienes la última versión.\n\n"
                    f"  Instalada: v{__version__}\n"
                    f"  Última publicada: {latest or '(no encontrada)'}\n"
                    f"  Repo: {info.get('repo', '?')}",
                )
                return
            size_mb = (info.get("asset_size") or 0) / (1024 * 1024)
            notes = info.get("body") or "(sin notas)"
            if not messagebox.askyesno(
                "Actualización disponible",
                f"Hay una versión nueva de DJ Tracks:\n\n"
                f"  Tu versión:  v{__version__}\n"
                f"  Nueva:       {info['latest']}\n"
                f"  Tamaño:      {size_mb:.1f} MB\n"
                f"  Asset:       {info.get('asset_name', '?')}\n\n"
                f"Notas:\n{notes[:400]}\n\n"
                f"¿Descargar e instalar ahora? La app se cerrará y "
                f"reabrirá automáticamente.",
            ):
                return
            # Frozen-build guard — from source we can't swap an .exe.
            if not app_updater.is_frozen():
                messagebox.showwarning(
                    "DJ Tracks",
                    "Esta build está ejecutándose desde el código fuente. "
                    "La actualización automática sólo funciona en el .exe "
                    "empaquetado.  Abre la página de la release en GitHub "
                    "y descárgala manualmente.",
                )
                try:
                    import webbrowser
                    webbrowser.open(info.get("url", ""))
                except Exception:
                    pass
                return
            _show_toast(f"⬇ Descargando {info['asset_name']}…", "info")
            threading.Thread(
                target=lambda: _do_download(info),
                daemon=True,
            ).start()

        def _do_download(info: dict) -> None:
            import tempfile
            dest = Path(tempfile.gettempdir()) / info["asset_name"]
            ok = app_updater.download_asset(info["asset_url"], dest)
            if not ok:
                self.after(0, lambda: messagebox.showerror(
                    "DJ Tracks",
                    "Falló la descarga.  Comprueba la conexión y vuelve a "
                    "intentarlo."))
                return
            # Swap on the main thread so the messagebox shows correctly
            # before the process exits.
            self.after(0, lambda: _do_apply(dest))

        def _do_apply(dest: Path) -> None:
            _show_toast("✓ Descarga completa — reiniciando…", "success")
            ok = app_updater.apply_update(dest)
            if not ok:
                messagebox.showerror(
                    "DJ Tracks",
                    "No se pudo aplicar la actualización.  El archivo "
                    f"descargado está en:\n\n{dest}\n\nÁbrelo manualmente.")

        _show_toast("🔍 Buscando actualizaciones de DJ Tracks…", "info")
        threading.Thread(target=_worker, daemon=True).start()

    def _handle_update_ytdlp(self) -> None:
        """Check PyPI and upgrade yt-dlp if a newer version is available."""
        from tkinter import messagebox

        def _worker() -> None:
            result = self._ctrl.update_ytdlp()
            self.after(0, lambda: self._after_update(result))

        # Feedback while the network + pip call runs (can take 10-60 s).
        self._update_dlg_active = True
        # Quick "started" toast — no blocking dialog while we work.
        try:
            top = self.winfo_toplevel()
            # Use the app's toast if available, else a small status line.
            if hasattr(top, "_toast"):
                top._toast("🔄 Buscando actualizaciones de yt-dlp…", "info")
        except Exception:
            pass

        threading.Thread(target=_worker, daemon=True).start()

    def _after_update(self, result: dict) -> None:
        """Show the user the outcome of the yt-dlp update."""
        from tkinter import messagebox
        status  = result.get("status", "error")
        message = result.get("message", "Sin respuesta")
        title   = "yt-dlp"
        if status == "updated":
            # The new yt-dlp is on disk but the running app still has the OLD
            # one loaded in memory — Python doesn't hot-reload C extensions.
            # Offer to restart so the user really gets the new version.
            wants_restart = messagebox.askyesno(
                title,
                message + "\n\n¿Reiniciar DJ Tracks ahora "
                          "para activar la nueva versión?",
                parent=self.winfo_toplevel(),
                default="yes",
            )
            if wants_restart:
                self._restart_app()
        elif status == "up-to-date":
            messagebox.showinfo(title, message, parent=self.winfo_toplevel())
        else:
            messagebox.showerror(title, message, parent=self.winfo_toplevel())

    def _restart_app(self) -> None:
        """Re-launch the current main.py in a fresh process, then quit."""
        import os as _os
        import subprocess as _sp
        import sys as _sys
        try:
            root_dir = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
            main_py  = _os.path.join(root_dir, "main.py")
            kwargs: dict = {}
            if _os.name == "nt":
                kwargs["creationflags"] = (
                    _sp.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
                    | 0x00000008                  # DETACHED_PROCESS
                )
            else:
                kwargs["start_new_session"] = True
            _sp.Popen(
                [_sys.executable, "-B", main_py],
                cwd=root_dir,
                stdout=_sp.DEVNULL, stderr=_sp.DEVNULL, stdin=_sp.DEVNULL,
                **kwargs,
            )
        except Exception:
            pass
        finally:
            # Close this instance — the new one is already starting.
            try:
                self.winfo_toplevel().destroy()
            except Exception:
                _os._exit(0)

    def _handle_donate(self) -> None:
        from ui.donations import show_donations
        show_donations(self.winfo_toplevel(), C)

    def _handle_show_setup_wizard(self) -> None:
        from ui.setup_wizard import show_setup_wizard
        # The wizard's "Ir a Ajustes" button is a no-op here (we're already
        # in Settings) — just close the dialog.
        show_setup_wizard(self.winfo_toplevel(), C, on_open_settings=None)

    def _handle_create_shortcut(self) -> None:
        from tkinter import messagebox
        try:
            from utils.shortcut import create_shortcut
            path = create_shortcut()
            messagebox.showinfo(
                "Acceso directo creado",
                f"Acceso directo creado en:\n{path}",
                parent=self.winfo_toplevel(),
            )
        except Exception as exc:
            messagebox.showerror(
                "Error",
                f"No se pudo crear el acceso directo:\n{exc}",
                parent=self.winfo_toplevel(),
            )

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
            "cross_platform_retry":    self._cross_retry_var.get(),
            "check_updates_on_startup": self._check_updates_var.get(),
            "cookies_browser":         ("" if self._cookies_var.get() == "(desactivado)"
                                           else self._cookies_var.get()),
            "threads":                 threads,
            "notify_on_complete":        self._notify_var.get(),
            "native_notify_on_complete": self._native_notify_var.get(),
            "open_folder_on_complete":   self._open_folder_var.get(),
            "sound_on_complete":         self._sound_var.get(),
            "dj_enrich":          self._dj_enrich_var.get(),
            "dj_getsongbpm_key":  self._dj_key_var.get().strip(),
            "dj_local_fallback":  self._dj_local_var.get(),
            "dj_filename":        self._dj_filename_var.get(),
            "dj_replaygain":      self._dj_replaygain_var.get(),
            "dj_quality_check":   self._dj_quality_var.get(),
            "dedupe_audio_fp":    self._dedup_var.get(),
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


class PlayerBar(ctk.CTkFrame):
    """Apple Music-style mini-player anchored above the status bar.

    Layout (left → right):
        [cover 56×56] [title / artist]  ⟨◂◂  ▶/⏸  ▸▸⟩  [elapsed •━━• total]  [🔊 vol]

    Hides itself when nothing has been loaded.  Reacts to AudioPlayer
    state changes via subscribe().
    """

    HEIGHT     = 78
    COVER_SIZE = 56

    def __init__(self, parent, **kw):
        super().__init__(parent, height=self.HEIGHT, fg_color=C["panel"],
                         corner_radius=0, **kw)
        self.pack_propagate(False)
        self._seeking = False
        self._tick_id: Optional[str] = None
        self._cover_cache_key: Optional[bytes] = None
        self._cover_img: Optional[ctk.CTkImage] = None
        self._placeholder_img: Optional[ctk.CTkImage] = None
        self._build()
        self._hide()

        from utils.audio_player import AudioPlayer
        AudioPlayer.get().subscribe(self._on_player_state)

    # ── UI ──────────────────────────────────────────────────────────────────
    def _build(self) -> None:
        # 1-pixel top border for separation from content
        top_border = ctk.CTkFrame(self, height=1, fg_color=C["border"], corner_radius=0)
        top_border.pack(fill="x", side="top")

        # ── Left: cover ─────────────────────────────────────────────────────
        left = ctk.CTkFrame(self, fg_color="transparent",
                            width=self.COVER_SIZE + 16)
        left.pack(side="left", fill="y", padx=(12, 0))
        left.pack_propagate(False)
        self._cover_lbl = ctk.CTkLabel(
            left, text="♪", font=_font(22, "bold"),
            text_color=C["text_dim"], fg_color=C["surface"],
            width=self.COVER_SIZE, height=self.COVER_SIZE, corner_radius=6,
            cursor="hand2")
        self._cover_lbl.place(relx=0.5, rely=0.5, anchor="center")
        self._cover_lbl.bind("<Button-1>", lambda _e: self._open_now_playing())
        self._now_playing_win: Optional["NowPlayingWindow"] = None

        # ── Right: volume ───────────────────────────────────────────────────
        right = ctk.CTkFrame(self, fg_color="transparent", width=140)
        right.pack(side="right", fill="y", padx=(0, 14))
        right.pack_propagate(False)
        ctk.CTkLabel(right, text="🔊", font=_font(11),
                     text_color=C["text_dim"]).pack(side="left", padx=(0, 6),
                                                     pady=(0, 0))
        self._vol = ctk.CTkSlider(
            right, from_=0, to=100, width=100, height=14,
            command=self._on_volume)
        self._vol.set(80)
        self._vol.pack(side="left", pady=(0, 0))

        # ── Center: title + controls + seek (stacked) ───────────────────────
        center = ctk.CTkFrame(self, fg_color="transparent")
        center.pack(side="left", fill="both", expand=True, padx=12, pady=8)

        # Row 1: title + artist on the left, transport on the right
        row1 = ctk.CTkFrame(center, fg_color="transparent")
        row1.pack(fill="x")

        info = ctk.CTkFrame(row1, fg_color="transparent")
        info.pack(side="left", fill="x", expand=True)
        self._title_lbl = ctk.CTkLabel(
            info, text="", font=_font(11, "bold"),
            text_color=C["text"], anchor="w", cursor="hand2")
        self._title_lbl.pack(anchor="w", fill="x")
        self._title_lbl.bind("<Button-1>", lambda _e: self._open_now_playing())
        self._artist_lbl = ctk.CTkLabel(
            info, text="", font=_font(9),
            text_color=C["text_dim"], anchor="w")
        self._artist_lbl.pack(anchor="w", fill="x")

        transport = ctk.CTkFrame(row1, fg_color="transparent")
        transport.pack(side="right")
        self._prev_btn = ctk.CTkButton(
            transport, text="⏮", width=30, height=28, font=_font(14, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text_mid"], corner_radius=6,
            command=self._prev)
        self._prev_btn.pack(side="left", padx=2)
        self._pp_btn = ctk.CTkButton(
            transport, text="▶", width=36, height=32, font=_font(16, "bold"),
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color=C["bg"], corner_radius=16,
            command=self._toggle_pause)
        self._pp_btn.pack(side="left", padx=4)
        self._next_btn = ctk.CTkButton(
            transport, text="⏭", width=30, height=28, font=_font(14, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text_mid"], corner_radius=6,
            command=self._next)
        self._next_btn.pack(side="left", padx=2)
        self._stop_btn = ctk.CTkButton(
            transport, text="■", width=28, height=28, font=_font(10, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text_dim"], corner_radius=6,
            command=self._stop)
        self._stop_btn.pack(side="left", padx=(8, 0))

        # Row 2: elapsed • seek • total
        row2 = ctk.CTkFrame(center, fg_color="transparent")
        row2.pack(fill="x", pady=(6, 0))
        self._elapsed = ctk.CTkLabel(row2, text="0:00", font=_font(8),
                                     text_color=C["text_dim"], width=32)
        self._elapsed.pack(side="left")
        self._seek = ctk.CTkSlider(
            row2, from_=0, to=1000, height=12,
            command=self._on_seek_drag)
        self._seek.set(0)
        self._seek.bind("<ButtonRelease-1>", self._on_seek_release)
        self._seek.bind("<Button-1>", self._on_seek_press)
        self._seek.pack(side="left", fill="x", expand=True, padx=6)
        self._total = ctk.CTkLabel(row2, text="0:00", font=_font(8),
                                   text_color=C["text_dim"], width=32)
        self._total.pack(side="left")

    # ── Visibility ──────────────────────────────────────────────────────────
    def _show(self) -> None:
        if not self.winfo_ismapped():
            self.pack(side="bottom", fill="x")

    def _hide(self) -> None:
        if self.winfo_ismapped():
            self.pack_forget()

    # ── Actions ─────────────────────────────────────────────────────────────
    def _toggle_pause(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().toggle_pause()

    def _stop(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().stop()

    def _open_now_playing(self) -> None:
        from utils.audio_player import AudioPlayer
        if AudioPlayer.get().current is None:
            return
        if self._now_playing_win is not None and self._now_playing_win.winfo_exists():
            self._now_playing_win.lift()
            self._now_playing_win.focus_force()
            return
        self._now_playing_win = NowPlayingWindow(self.winfo_toplevel())

    def _prev(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().prev()

    def _next(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().next()

    def _on_volume(self, value: float) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().set_volume(value / 100.0)

    def _on_seek_press(self, _e=None) -> None:
        self._seeking = True

    def _on_seek_drag(self, value: float) -> None:
        from utils.audio_player import AudioPlayer
        dur = AudioPlayer.get().duration
        if dur > 0:
            self._elapsed.configure(text=_fmt_mmss(dur * (value / 1000.0)))

    def _on_seek_release(self, _e=None) -> None:
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        dur = player.duration
        if dur > 0:
            target = dur * (self._seek.get() / 1000.0)
            player.seek(target)
        self._seeking = False

    # ── State sync ──────────────────────────────────────────────────────────
    def _on_player_state(self) -> None:
        try:
            self.after(0, self._refresh)
        except Exception:
            pass

    def _refresh(self) -> None:
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        if player.current is None:
            self._hide()
            self._stop_tick()
            return
        self._show()
        # Title / artist (fall back to filename if tags are missing)
        title  = player.title  or player.current.stem
        artist = player.artist or ""
        self._title_lbl.configure(text=title[:50])
        self._artist_lbl.configure(text=artist[:50] or "—")
        # Cover
        self._refresh_cover(player.cover_bytes)
        # Transport
        self._pp_btn.configure(text="⏸" if not player.paused else "▶")
        self._prev_btn.configure(state="normal" if player.has_prev else "disabled")
        self._next_btn.configure(state="normal" if player.has_next else "disabled")
        # Volume slider stays in sync if changed programmatically
        try:
            self._vol.set(int(player.volume * 100))
        except Exception:
            pass
        dur = player.duration
        self._total.configure(text=_fmt_mmss(dur) if dur > 0 else "--:--")
        self._start_tick()

    def _refresh_cover(self, data: Optional[bytes]) -> None:
        """Update the cover image; cache by raw bytes identity so we don't
        re-decode on every state change."""
        if data is self._cover_cache_key and self._cover_img is not None:
            return
        self._cover_cache_key = data
        if not data:
            self._cover_img = None
            self._cover_lbl.configure(image=None, text="♪")
            return
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((self.COVER_SIZE * 2, self.COVER_SIZE * 2),
                          Image.Resampling.LANCZOS)
            self._cover_img = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(self.COVER_SIZE, self.COVER_SIZE))
            self._cover_lbl.configure(image=self._cover_img, text="")
        except Exception:
            self._cover_img = None
            self._cover_lbl.configure(image=None, text="♪")

    # ── Progress tick ───────────────────────────────────────────────────────
    def _start_tick(self) -> None:
        if self._tick_id is not None:
            return
        self._tick_id = self.after(500, self._tick)

    def _stop_tick(self) -> None:
        if self._tick_id is not None:
            try:
                self.after_cancel(self._tick_id)
            except Exception:
                pass
            self._tick_id = None

    def _tick(self) -> None:
        self._tick_id = None
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        if player.current is None:
            return
        pos = player.get_position()
        dur = player.duration
        if not self._seeking:
            if dur > 0:
                self._seek.set(min(1000, (pos / dur) * 1000))
            self._elapsed.configure(text=_fmt_mmss(pos))
        # Auto-advance when the song ends
        if (dur > 0 and pos >= dur - 0.5
                and not player.paused and player.has_next):
            player.next()
        if not player.paused:
            self._tick_id = self.after(500, self._tick)
        else:
            self._tick_id = self.after(800, self._tick)


def _fmt_mmss(seconds: float) -> str:
    if seconds is None or seconds < 0:
        return "0:00"
    s = int(seconds)
    return f"{s // 60}:{s % 60:02d}"


class NowPlayingWindow(ctk.CTkToplevel):
    """Full-screen "Now Playing" view, Apple Music style.

    Big square cover, large title / artist underneath, transport
    controls + scrubber.  Closes with Esc or by clicking ✕.  Tracks the
    AudioPlayer so swapping songs or pressing prev/next from anywhere
    refreshes the view live.
    """

    COVER_SIZE = 360

    def __init__(self, parent):
        super().__init__(parent)
        self.title("Now Playing")
        self.geometry("520x720")
        self.minsize(440, 640)
        self.configure(fg_color=C["bg"])
        try:
            self.transient(parent)
        except Exception:
            pass

        self._seeking = False
        self._tick_id: Optional[str] = None
        self._cover_cache_key: Optional[bytes] = None
        self._cover_img: Optional[ctk.CTkImage] = None
        self._build()
        self.bind("<Escape>", lambda _e: self.destroy())
        self.protocol("WM_DELETE_WINDOW", self._on_close)

        from utils.audio_player import AudioPlayer
        AudioPlayer.get().subscribe(self._on_player_state)
        self._refresh()

    def _build(self) -> None:
        # Close button (top-right)
        top = ctk.CTkFrame(self, fg_color="transparent", height=34)
        top.pack(fill="x", padx=10, pady=(8, 0))
        top.pack_propagate(False)
        ctk.CTkLabel(top, text="NOW PLAYING",
                     font=_font(9, "bold"),
                     text_color=C["text_dim"]).pack(side="left", padx=6)
        ctk.CTkButton(top, text="✕", width=30, height=26,
                      font=_font(13, "bold"),
                      fg_color="transparent", hover_color=C["surface"],
                      text_color=C["text_mid"], corner_radius=6,
                      command=self._on_close).pack(side="right")

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=40, pady=(8, 16))

        # Cover — a sunken card to make it pop on a dark bg
        cover_card = ctk.CTkFrame(
            body, fg_color=C["surface"], corner_radius=14,
            width=self.COVER_SIZE + 4, height=self.COVER_SIZE + 4)
        cover_card.pack(pady=(20, 24))
        cover_card.pack_propagate(False)
        self._cover_lbl = ctk.CTkLabel(
            cover_card, text="♪", font=_font(80, "bold"),
            text_color=C["text_dim"],
            width=self.COVER_SIZE, height=self.COVER_SIZE,
            corner_radius=12)
        self._cover_lbl.place(relx=0.5, rely=0.5, anchor="center")

        # Title + artist
        self._title_lbl = ctk.CTkLabel(
            body, text="", font=_font(18, "bold"),
            text_color=C["text"], anchor="center", justify="center")
        self._title_lbl.pack(fill="x", pady=(0, 4))
        self._artist_lbl = ctk.CTkLabel(
            body, text="", font=_font(12),
            text_color=C["text_dim"], anchor="center", justify="center")
        self._artist_lbl.pack(fill="x", pady=(0, 22))

        # Scrubber row
        scrub_row = ctk.CTkFrame(body, fg_color="transparent")
        scrub_row.pack(fill="x", padx=4)
        self._seek = ctk.CTkSlider(
            scrub_row, from_=0, to=1000, height=14,
            command=self._on_seek_drag)
        self._seek.set(0)
        self._seek.bind("<ButtonRelease-1>", self._on_seek_release)
        self._seek.bind("<Button-1>", self._on_seek_press)
        self._seek.pack(fill="x", pady=(0, 4))

        time_row = ctk.CTkFrame(body, fg_color="transparent")
        time_row.pack(fill="x", padx=4)
        self._elapsed = ctk.CTkLabel(time_row, text="0:00", font=_font(9),
                                     text_color=C["text_dim"])
        self._elapsed.pack(side="left")
        self._total = ctk.CTkLabel(time_row, text="0:00", font=_font(9),
                                   text_color=C["text_dim"])
        self._total.pack(side="right")

        # Transport
        transport = ctk.CTkFrame(body, fg_color="transparent")
        transport.pack(pady=20)
        self._prev_btn = ctk.CTkButton(
            transport, text="⏮", width=50, height=44, font=_font(22, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text"], corner_radius=22,
            command=self._prev)
        self._prev_btn.pack(side="left", padx=10)
        self._pp_btn = ctk.CTkButton(
            transport, text="▶", width=64, height=56, font=_font(26, "bold"),
            fg_color=C["accent"], hover_color=C["accent_dim"],
            text_color=C["bg"], corner_radius=28,
            command=self._toggle_pause)
        self._pp_btn.pack(side="left", padx=14)
        self._next_btn = ctk.CTkButton(
            transport, text="⏭", width=50, height=44, font=_font(22, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["text"], corner_radius=22,
            command=self._next)
        self._next_btn.pack(side="left", padx=10)

        # Volume
        vol_row = ctk.CTkFrame(body, fg_color="transparent")
        vol_row.pack(fill="x", padx=20, pady=(6, 0))
        ctk.CTkLabel(vol_row, text="🔈", font=_font(12),
                     text_color=C["text_dim"]).pack(side="left", padx=(0, 6))
        self._vol = ctk.CTkSlider(
            vol_row, from_=0, to=100, height=14,
            command=self._on_volume)
        self._vol.set(80)
        self._vol.pack(side="left", fill="x", expand=True)
        ctk.CTkLabel(vol_row, text="🔊", font=_font(12),
                     text_color=C["text_dim"]).pack(side="left", padx=(6, 0))

    # ── Actions ─────────────────────────────────────────────────────────────
    def _toggle_pause(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().toggle_pause()

    def _prev(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().prev()

    def _next(self) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().next()

    def _on_volume(self, value: float) -> None:
        from utils.audio_player import AudioPlayer
        AudioPlayer.get().set_volume(value / 100.0)

    def _on_seek_press(self, _e=None) -> None:
        self._seeking = True

    def _on_seek_drag(self, value: float) -> None:
        from utils.audio_player import AudioPlayer
        dur = AudioPlayer.get().duration
        if dur > 0:
            self._elapsed.configure(text=_fmt_mmss(dur * (value / 1000.0)))

    def _on_seek_release(self, _e=None) -> None:
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        dur = player.duration
        if dur > 0:
            player.seek(dur * (self._seek.get() / 1000.0))
        self._seeking = False

    # ── State sync ──────────────────────────────────────────────────────────
    def _on_player_state(self) -> None:
        try:
            if self.winfo_exists():
                self.after(0, self._refresh)
        except Exception:
            pass

    def _refresh(self) -> None:
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        if player.current is None:
            self.destroy()
            return
        title  = player.title or player.current.stem
        artist = player.artist or "—"
        self._title_lbl.configure(text=title[:64])
        self._artist_lbl.configure(text=artist[:64])
        self._refresh_cover(player.cover_bytes)
        self._pp_btn.configure(text="⏸" if not player.paused else "▶")
        self._prev_btn.configure(state="normal" if player.has_prev else "disabled")
        self._next_btn.configure(state="normal" if player.has_next else "disabled")
        try:
            self._vol.set(int(player.volume * 100))
        except Exception:
            pass
        dur = player.duration
        self._total.configure(text=_fmt_mmss(dur) if dur > 0 else "--:--")
        self._start_tick()

    def _refresh_cover(self, data: Optional[bytes]) -> None:
        if data is self._cover_cache_key and self._cover_img is not None:
            return
        self._cover_cache_key = data
        if not data:
            self._cover_img = None
            self._cover_lbl.configure(image=None, text="♪")
            return
        try:
            import io
            from PIL import Image
            img = Image.open(io.BytesIO(data)).convert("RGB")
            img.thumbnail((self.COVER_SIZE * 2, self.COVER_SIZE * 2),
                          Image.Resampling.LANCZOS)
            self._cover_img = ctk.CTkImage(
                light_image=img, dark_image=img,
                size=(self.COVER_SIZE, self.COVER_SIZE))
            self._cover_lbl.configure(image=self._cover_img, text="")
        except Exception:
            self._cover_img = None
            self._cover_lbl.configure(image=None, text="♪")

    def _start_tick(self) -> None:
        if self._tick_id is not None:
            return
        self._tick_id = self.after(500, self._tick)

    def _tick(self) -> None:
        self._tick_id = None
        try:
            if not self.winfo_exists():
                return
        except Exception:
            return
        from utils.audio_player import AudioPlayer
        player = AudioPlayer.get()
        if player.current is None:
            self.destroy()
            return
        pos = player.get_position()
        dur = player.duration
        if not self._seeking:
            if dur > 0:
                self._seek.set(min(1000, (pos / dur) * 1000))
            self._elapsed.configure(text=_fmt_mmss(pos))
        delay = 500 if not player.paused else 800
        self._tick_id = self.after(delay, self._tick)

    def _on_close(self) -> None:
        if self._tick_id is not None:
            try:
                self.after_cancel(self._tick_id)
            except Exception:
                pass
            self._tick_id = None
        self.destroy()


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
        self._root.minsize(*self.APP_MIN_SIZE)
        self._root.configure(fg_color=C["bg"])

        # Restore window geometry from last session (size + position) when
        # available; otherwise use the default centred geometry.
        saved_geom  = controller.get_config("window_geometry", "")
        saved_state = controller.get_config("window_state",    "normal")
        if saved_geom and isinstance(saved_geom, str) and "x" in saved_geom:
            try:
                self._root.geometry(saved_geom)
            except Exception:
                self._root.geometry(self.APP_GEOMETRY)
        else:
            self._root.geometry(self.APP_GEOMETRY)
        if saved_state == "zoomed":
            try:
                self._root.state("zoomed")
            except Exception:
                pass

        self._panels: Dict[str, ctk.CTkFrame] = {}
        self._content_area: Optional[ctk.CTkFrame] = None

        self._set_icon()
        self._build()

        # Register the UI callback via the public setter.
        self._ctrl.set_on_task_update(self._download_panel.on_task_update)

        # Drag-and-drop: dropping a URL on the search bar triggers a search.
        self._search_panel.setup_drag_drop(self._root)

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

        ctk.CTkButton(
            self._topbar, text="♥", width=32, height=28, font=_font(13, "bold"),
            fg_color="transparent", hover_color=C["surface"],
            text_color=C["error"], corner_radius=6,
            command=self._open_donations).pack(side="right", padx=(0, 12))

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

        # Mini player bar (sits between status bar and content; hides itself
        # until the user presses ▶ on a history row).
        self._player_bar = PlayerBar(self._root)
        self._player_bar.pack(side="bottom", fill="x")
        self._player_bar.pack_forget()
        self._statusbar.pack_propagate(False)
        ctk.CTkLabel(self._statusbar,
                     text="DJ Tracks  ·  yt-dlp  ·  Spotify  ·  Apple Music  ·  SoundCloud",
                     font=_font(8), text_color=C["text_dim"]).pack(side="left", padx=12)
        self._status_lbl = ctk.CTkLabel(self._statusbar, text="", font=_font(8))
        self._status_lbl.pack(side="right", padx=12)
        self.refresh_status()

        self._show_panel("dashboard")
        self._bind_shortcuts()

        # Background update check on startup (toggleable, default ON).
        # Runs ~3 s after the window is up so it never delays the splash.
        if self._ctrl._config.get("check_updates_on_startup", True):
            self._root.after(3000, self._kick_startup_update_check)

    def _kick_startup_update_check(self) -> None:
        """Background GitHub poll on launch.  Quiet on failure; shows
        a single toast (with click-to-open-settings) when a newer
        version exists."""
        from utils import app_updater

        def _worker() -> None:
            info = app_updater.check_for_update(__version__)
            if not info.get("available"):
                return
            latest = info["latest"]
            # Marshal back to the Tk thread (app_updater already logs the
            # outcome via its own module logger).
            self._root.after(0, lambda: self._toast(
                f"🆕 Nueva versión disponible: {latest}  ·  "
                f"Ajustes → Buscar actualizaciones",
                kind="info",
                ms=6500,
            ))

        threading.Thread(target=_worker, daemon=True,
                         name="dj-startup-update-check").start()

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
            on_dashboard_refresh=lambda: self._dashboard_panel.refresh(),
            on_redownload=self._on_history_redownload)
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
        # enqueue_result expands albums/sets into all their tracks; single
        # tracks enqueue as-is. Runs on whatever thread called us (the search
        # panel already backgrounds multi-select adds).
        from core.controller import DonorGateBlocked
        try:
            n = self._ctrl.enqueue_result(track)
        except DonorGateBlocked:
            self._root.after(0, self._show_lockout_dialog)
            return
        name = f"{track.artist_str} — {track.title}"
        if getattr(track, "is_album", False):
            self._root.after(0, lambda: self._toast(
                f"💿 Álbum: {n} pista{'s' if n != 1 else ''} en cola" if n
                else f"No se pudo expandir el álbum «{track.title[:40]}»",
                "success" if n else "error"))
        else:
            self._root.after(0, lambda: self._toast(f"Añadido: {name[:60]}"))

    # ── History re-download ────────────────────────────────────────────────────

    def _on_history_redownload(self, record) -> None:
        """Re-download a track from a history record.

        The record carries title, artist, album and platform but no source URL,
        so we run a 1-result search on the original platform (falling back to
        "auto" if that platform is unavailable) and enqueue the best match.
        Runs in a background thread to avoid blocking the UI on the search.
        """
        artist = record.artist or ""
        title  = record.title  or ""
        if not (artist or title):
            self._toast("Registro sin artista ni título — no se puede redescargar", "error")
            return

        query = f"{artist} - {title}".strip(" -") or title
        self._toast(f"↻ Buscando: {title[:55]}", "info")

        def _worker() -> None:
            try:
                results = self._ctrl.search(query, platform_str=record.platform or "auto", limit=1)
                # Fallback to a fan-out search if the original platform is
                # unavailable (e.g. Spotify with no credentials).
                if not results and record.platform:
                    results = self._ctrl.search(query, platform_str="auto", limit=1)
            except Exception as exc:
                self._root.after(0, lambda: self._toast(
                    f"Error en la búsqueda: {exc}", "error"))
                return

            if not results:
                self._root.after(0, lambda: self._toast(
                    f"No se encontró «{title[:50]}» para redescargar", "error"))
                return

            track = results[0]
            from core.controller import DonorGateBlocked
            try:
                self._ctrl.add_to_queue(track)
            except DonorGateBlocked:
                self._root.after(0, self._show_lockout_dialog)
                return
            name = f"{track.artist_str} — {track.title}"
            self._root.after(0, lambda: self._toast(
                f"↻ Reencolado: {name[:55]}", "success"))

        threading.Thread(target=_worker, daemon=True).start()

    # ── Task completion side-effects (toggleable from Settings) ───────────────

    def _on_task_complete(self, task: DownloadTask) -> None:
        """Dispatch optional per-completion actions according to user prefs."""
        name = f"{task.track.artist_str} — {task.track.title}"

        if self._ctrl.get_config("notify_on_complete", True):
            self._toast(f"✓ Listo: {name[:55]}", "success")

        # Native OS notification (persists when window is minimised / hidden).
        if self._ctrl.get_config("native_notify_on_complete", False):
            from utils.notifications import notify
            notify("DJ Tracks — Descarga completa", name[:140])

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

    # ── Freemium gate ──────────────────────────────────────────────────────

    def _show_lockout_dialog(self) -> None:
        """Modal shown when the user hits the free-download limit.
        Offers two paths: donate (opens Ko-fi) or, if already donated,
        link Discord to unlock."""
        if getattr(self, "_lockout_win", None) and self._lockout_win.winfo_exists():
            self._lockout_win.lift()
            self._lockout_win.focus_force()
            return
        self._lockout_win = LockoutDialog(self._root, self)



    def _toast(self, message: str, kind: str = "info", ms: int = 2800) -> None:
        Toast(self._root, message, kind=kind, ms=ms)

    def _open_donations(self) -> None:
        from ui.donations import show_donations
        show_donations(self._root, C)

    def _save_geometry(self) -> None:
        """Persist window size, position, and maximised state."""
        try:
            state = self._root.state()
            payload = {"window_state": state}
            if state == "normal":
                payload["window_geometry"] = self._root.geometry()
            self._ctrl.save_config(payload)
        except Exception:
            pass

    def _quit(self) -> None:
        self._save_geometry()
        self._ctrl.shutdown()
        self._root.quit()

    def run(self) -> None:
        """Start the Tkinter main loop."""
        self._root.protocol("WM_DELETE_WINDOW", self._quit)
        self._root.mainloop()


class LockoutDialog(ctk.CTkToplevel):
    """Friendly 'free tier exhausted' modal.

    Two paths:
      1. Donar en Ko-fi — opens the user's browser to the donation page.
      2. Conectar Discord — kicks off the OAuth flow and polls the
         backend until it returns a donor flag.

    Once the donor check returns True the dialog auto-closes.
    """

    def __init__(self, parent, app):
        super().__init__(parent)
        self._app = app
        self.title("Apoya DJ Tracks")
        self.geometry("520x540")
        self.resizable(False, False)
        self.configure(fg_color=C["bg"])
        try:
            self.transient(parent)
            self.grab_set()
        except Exception:
            pass
        self._poll_id: Optional[str] = None
        self._oauth_token: str = ""
        self._build()
        self.bind("<Escape>", lambda _e: self._close())
        self.protocol("WM_DELETE_WINDOW", self._close)

    def _build(self) -> None:
        from utils.donor_gate import get_state, FREE_LIMIT
        st = get_state()

        body = ctk.CTkFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True, padx=30, pady=24)

        ctk.CTkLabel(body, text="🎧",
                     font=_font(48), text_color=C["accent"]).pack(pady=(4, 8))
        ctk.CTkLabel(body, text="Has llegado al límite gratuito",
                     font=_font(17, "bold"),
                     text_color=C["text"]).pack()
        ctk.CTkLabel(body,
                     text=f"Has descargado {st['download_count']} tracks. "
                          f"El tier gratuito incluye {FREE_LIMIT}.",
                     font=_font(11),
                     text_color=C["text_dim"]).pack(pady=(4, 18))

        ctk.CTkLabel(body,
                     text="DJ Tracks es de uso personal y se mantiene gracias a "
                          "donaciones puntuales. Con una sola donación desbloqueas "
                          "descargas ilimitadas para siempre y entras al canal de "
                          "donantes en Discord.",
                     font=_font(11), text_color=C["text_mid"],
                     wraplength=440, justify="center").pack(pady=(0, 20))

        ctk.CTkButton(body, text="☕  Donar en Ko-fi",
                      height=42, font=_font(13, "bold"),
                      fg_color=C["accent"], hover_color=C["accent_dim"],
                      text_color=C["bg"], corner_radius=10,
                      command=self._donate).pack(fill="x", pady=(0, 8))
        ctk.CTkLabel(body,
                     text="Te abrirá Ko-fi en el navegador. Tras donar, vuelve "
                          "aquí y pulsa abajo para vincular Discord.",
                     font=_font(9), text_color=C["text_dim"],
                     wraplength=440).pack(pady=(0, 16))

        ctk.CTkButton(body, text="🔗  Ya doné — vincular Discord",
                      height=40, font=_font(12, "bold"),
                      fg_color=C["surface"], hover_color=C["card_hover"],
                      text_color=C["text"], corner_radius=10,
                      border_width=1, border_color=C["border"],
                      command=self._link_discord).pack(fill="x")

        self._status_lbl = ctk.CTkLabel(body, text="",
                                        font=_font(10),
                                        text_color=C["text_dim"])
        self._status_lbl.pack(pady=(12, 0))

        ctk.CTkButton(body, text="Cerrar", height=28,
                      font=_font(10), fg_color="transparent",
                      hover_color=C["surface"], text_color=C["text_dim"],
                      corner_radius=6, command=self._close,
                      ).pack(side="bottom", pady=(12, 0))

    def _donate(self) -> None:
        import webbrowser
        from utils.donor_client import kofi_url
        webbrowser.open(kofi_url())
        self._status_lbl.configure(
            text="Te abrimos Ko-fi. Cuando termines, pulsa «Ya doné»."
        )

    def _link_discord(self) -> None:
        import uuid
        from utils import donor_client
        self._oauth_token = uuid.uuid4().hex
        opened = donor_client.open_oauth_flow(self._oauth_token)
        if not opened:
            self._status_lbl.configure(
                text="No se pudo abrir el navegador. Comprueba tu configuración.",
                text_color=C["error"])
            return
        self._status_lbl.configure(
            text="🔄 Esperando confirmación en el navegador…",
            text_color=C["accent"])
        self._schedule_poll()

    def _schedule_poll(self, delay_ms: int = 2000) -> None:
        if self._poll_id is not None:
            return
        self._poll_id = self.after(delay_ms, self._poll)

    def _poll(self) -> None:
        self._poll_id = None
        if not self.winfo_exists():
            return
        from utils import donor_client, donor_gate
        result = donor_client.poll_oauth_result(self._oauth_token)
        if result is None:
            self._schedule_poll(2500)
            return
        donor_gate.set_donor(
            bool(result.get("donor", False)),
            discord_user_id  = result.get("discord_user_id", ""),
            discord_username = result.get("discord_username", ""),
        )
        if result.get("donor"):
            self._status_lbl.configure(
                text=f"✓ ¡Verificado como Donor! Gracias, {result.get('discord_username','')}.",
                text_color=C["success"])
            self.after(1800, self._close)
        else:
            self._status_lbl.configure(
                text="No te encontramos el rol Donor todavía. Si acabas de "
                     "donar, espera unos segundos y vuelve a intentarlo.",
                text_color=C["warning"])

    def _close(self) -> None:
        if self._poll_id is not None:
            try:
                self.after_cancel(self._poll_id)
            except Exception:
                pass
            self._poll_id = None
        try:
            self.grab_release()
        except Exception:
            pass
        self.destroy()
