"""
ui/donations.py
================
Optional crypto-donation dialog.

The wallet list is intentionally **empty by default** so the
distributed app doesn't carry someone else's addresses.  Replace the
placeholder entries in :data:`CRYPTO_ADDRESSES` with your own before
distributing builds.

Renders a polished CustomTkinter ``CTkToplevel`` with:

- one button per coin (using the coin's brand colour),
- click on a coin → modal with full address + copy button,
- optional QR code (generated on-the-fly when ``qrcode`` is installed),
- safe fallback text when the wallet hasn't been configured yet.
"""
from __future__ import annotations

import io

import customtkinter as ctk

# ─────────────────────────────────────────────────────────────────────────────
# Configure your own wallet addresses here.  Leave any line as "" to hide
# that coin from the dialog.
# ─────────────────────────────────────────────────────────────────────────────

WalletEntry = str | dict[str, str]   # str = address; dict for memo-aware

CRYPTO_ADDRESSES: dict[str, WalletEntry] = {
    "BTC":   "",
    "ETH":   "",
    "BNB":   "",
    "SOL":   "",
    "DOGE":  "",
    "LTC":   "",
    "TRX":   "",
    "XRP":   "",
}

CRYPTO_META: dict[str, dict[str, str]] = {
    "BTC":   {"color": "#F7931A", "symbol": "₿", "network": "Bitcoin"},
    "ETH":   {"color": "#627EEA", "symbol": "Ξ", "network": "Ethereum (ERC-20)"},
    "BNB":   {"color": "#F3BA2F", "symbol": "⬡", "network": "BNB Smart Chain"},
    "SOL":   {"color": "#9945FF", "symbol": "◎", "network": "Solana"},
    "DOGE":  {"color": "#C2A633", "symbol": "Ð", "network": "Dogecoin"},
    "LTC":   {"color": "#BFBBBB", "symbol": "Ł", "network": "Litecoin"},
    "TRX":   {"color": "#E50915", "symbol": "◈", "network": "TRON"},
    "XRP":   {"color": "#00AAE4", "symbol": "✦", "network": "XRP Ledger"},
}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _copy(root, text: str) -> None:
    try:
        root.clipboard_clear()
        root.clipboard_append(text)
    except Exception:
        pass


def _qr_image(data: str, fg: str, size: int = 220):
    """Return a CTkImage with the rendered QR code, or None if qrcode missing."""
    try:
        import qrcode
        from PIL import Image
    except Exception:
        return None
    try:
        qr = qrcode.QRCode(version=1, box_size=8, border=3)
        qr.add_data(data)
        qr.make(fit=True)
        img = qr.make_image(fill_color=fg, back_color="white")
        buf = io.BytesIO()
        img.save(buf, "PNG")
        buf.seek(0)
        pil = Image.open(buf).convert("RGB").resize((size, size), Image.Resampling.LANCZOS)
        return ctk.CTkImage(light_image=pil, dark_image=pil, size=(size, size))
    except Exception:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Public entry point
# ─────────────────────────────────────────────────────────────────────────────

def show_donations(root, palette: dict[str, str]) -> None:
    """
    Open the donations modal on top of *root* using the active *palette*.

    Args:
        root:    Parent ``ctk.CTk`` window.
        palette: Active theme palette (the global ``C`` dict from ``ui.gui``).
    """
    C = palette

    win = ctk.CTkToplevel(root)
    win.title("Apoya el proyecto")
    win.configure(fg_color=C["bg"])
    win.transient(root)
    win.grab_set()

    # Top accent strip.
    ctk.CTkFrame(win, height=3, fg_color=C["accent"], corner_radius=0).pack(fill="x")

    # Header.
    hdr = ctk.CTkFrame(win, fg_color=C["panel"], corner_radius=0)
    hdr.pack(fill="x")
    ctk.CTkLabel(
        hdr, text="♥  Apoya el desarrollo",
        font=ctk.CTkFont(size=15, weight="bold"),
        text_color=C["accent"]).pack(padx=20, pady=12, anchor="w")

    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(fill="both", expand=True, padx=20, pady=14)

    ctk.CTkLabel(
        body,
        text="Si DJ Tracks te resulta útil, puedes invitarme a un café "
             "en cualquiera de estas redes.\nGracias por usar la app  ♥",
        font=ctk.CTkFont(size=11), text_color=C["text_mid"],
        wraplength=380, justify="center",
    ).pack(pady=(0, 12))

    # Coin grid.
    grid = ctk.CTkFrame(body, fg_color="transparent")
    grid.pack()

    coins = [c for c in CRYPTO_ADDRESSES if c in CRYPTO_META]
    cols  = 4
    for idx, coin in enumerate(coins):
        meta  = CRYPTO_META[coin]
        color = meta["color"]
        btn = ctk.CTkButton(
            grid, text=f"{meta['symbol']} {coin}",
            width=80, height=36, font=ctk.CTkFont(size=11, weight="bold"),
            fg_color=C["card"], hover_color=color,
            text_color=color, corner_radius=8,
            border_width=1, border_color=color,
            command=lambda c=coin: _show_one(win, C, c),
        )
        btn.grid(row=idx // cols, column=idx % cols, padx=4, pady=4)

    ctk.CTkButton(
        win, text="Cerrar", width=120, height=32,
        font=ctk.CTkFont(size=11, weight="bold"),
        fg_color=C["surface"], hover_color=C["card_hover"],
        text_color=C["text"], corner_radius=6,
        command=win.destroy,
    ).pack(pady=(8, 16))

    # Centre over parent.
    win.update_idletasks()
    rx, ry = root.winfo_x(), root.winfo_y()
    rw, rh = root.winfo_width(), root.winfo_height()
    ww, wh = win.winfo_width(), win.winfo_height()
    win.geometry(f"+{rx + (rw - ww)//2}+{ry + (rh - wh)//2}")


def _show_one(parent, C: dict[str, str], coin: str) -> None:
    """Modal showing one coin's address, optional QR, and copy buttons."""
    entry = CRYPTO_ADDRESSES.get(coin, "")
    if isinstance(entry, dict):
        addr = entry.get("address", "")
        memo = entry.get("memo", "")
    else:
        addr = entry
        memo = ""

    meta    = CRYPTO_META.get(coin, {"color": C["accent"], "symbol": "", "network": coin})
    color   = meta["color"]
    symbol  = meta["symbol"]
    network = meta.get("network", coin)

    win = ctk.CTkToplevel(parent)
    win.title(f"Donar {symbol} {coin}")
    win.configure(fg_color=C["bg"])
    win.transient(parent)
    win.grab_set()

    ctk.CTkFrame(win, height=3, fg_color=color, corner_radius=0).pack(fill="x")

    hdr = ctk.CTkFrame(win, fg_color=C["panel"], corner_radius=0)
    hdr.pack(fill="x")
    ctk.CTkLabel(hdr, text=f"{symbol}  {coin}",
                 font=ctk.CTkFont(size=18, weight="bold"),
                 text_color=color).pack(anchor="w", padx=20, pady=(10, 0))
    ctk.CTkLabel(hdr, text=f"Red: {network}",
                 font=ctk.CTkFont(size=9),
                 text_color=C["text_dim"]).pack(anchor="w", padx=20, pady=(0, 10))

    body = ctk.CTkFrame(win, fg_color="transparent")
    body.pack(padx=20, pady=14)

    if not addr:
        ctk.CTkLabel(
            body,
            text="🚧  Dirección no configurada todavía.\n\nEl desarrollador puede añadirla\nen ui/donations.py.",
            font=ctk.CTkFont(size=11), text_color=C["text_mid"],
            justify="center",
        ).pack(pady=20)
    else:
        qr_data = f"stellar:{addr}?memo={memo}" if (coin == "XLM" and memo) else addr
        qr_img  = _qr_image(qr_data, color, size=220)
        if qr_img is not None:
            qr_label = ctk.CTkLabel(body, text="", image=qr_img,
                                    fg_color="white", corner_radius=6)
            qr_label.pack(pady=(4, 10))
            qr_label._qr_ref = qr_img   # prevent GC

        # Address box.
        addr_text = addr if not memo else f"{addr}\n\nMemo: {memo}"
        addr_box = ctk.CTkTextbox(
            body, width=360, height=80, font=ctk.CTkFont(family="Consolas", size=10),
            fg_color=C["card"], text_color=C["text"],
            border_width=1, border_color=C["border"],
            wrap="word", activate_scrollbars=False,
        )
        addr_box.insert("1.0", addr_text)
        addr_box.configure(state="disabled")
        addr_box.pack(fill="x", pady=(0, 8))

        copy_row = ctk.CTkFrame(body, fg_color="transparent")
        copy_row.pack(pady=4)
        ctk.CTkButton(
            copy_row, text="📋  Copiar dirección",
            width=160, height=32,
            font=ctk.CTkFont(size=10, weight="bold"),
            fg_color=color, hover_color=color, text_color="#FFF",
            corner_radius=6,
            command=lambda: _copy(parent.winfo_toplevel(), addr),
        ).pack(side="left", padx=4)
        if memo:
            ctk.CTkButton(
                copy_row, text="📋  Copiar memo",
                width=130, height=32,
                font=ctk.CTkFont(size=10, weight="bold"),
                fg_color=C["surface"], hover_color=C["card_hover"],
                text_color=C["text"], corner_radius=6,
                command=lambda: _copy(parent.winfo_toplevel(), memo),
            ).pack(side="left", padx=4)

    ctk.CTkButton(
        win, text="Cerrar", width=100, height=28,
        font=ctk.CTkFont(size=10),
        fg_color=C["surface"], hover_color=C["card_hover"],
        text_color=C["text_mid"], corner_radius=5,
        command=win.destroy,
    ).pack(pady=(0, 16))

    win.update_idletasks()
    px, py = parent.winfo_x(), parent.winfo_y()
    pw, ph = parent.winfo_width(), parent.winfo_height()
    ww, wh = win.winfo_width(), win.winfo_height()
    win.geometry(f"+{px + (pw - ww)//2}+{py + (ph - wh)//2}")
