# -*- mode: python ; coding: utf-8 -*-
"""
PyInstaller spec for DJ Tracks.

Bundles:
  - main.py + all project modules
  - ffmpeg.exe (placed next to the bundled binary)
  - assets/ (icon, logo)
  - CustomTkinter data files
  - mutagen submodules (dynamically imported by format)
  - PIL ImageTk support

Build with:
    py -m PyInstaller --noconfirm --clean build/dj_tracks.spec
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

ROOT = Path(SPECPATH).parent

# ── Bundled data ──────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files("customtkinter")

# ffmpeg goes to the bundle root so audio_downloader._find_ffmpeg picks it up.
if (ROOT / "ffmpeg.exe").exists():
    datas.append((str(ROOT / "ffmpeg.exe"), "."))

# Icons and logos.
if (ROOT / "assets").exists():
    datas.append((str(ROOT / "assets"), "assets"))

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = []
hiddenimports += collect_submodules("mutagen")
hiddenimports += [
    "PIL._tkinter_finder",
    "PIL.ImageTk",
]

# ── Modules to leave out (huge & unused at runtime) ───────────────────────────
excludes = [
    "pytest",
    "spotdl",          # only used for ffmpeg detection fallback; not at runtime
    "tests",
    "matplotlib",
    "numpy.tests",
    "pandas",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data)

icon_path = ROOT / "assets" / "icon.ico"

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="DJ Tracks",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,                                  # UPX trips antivirus heuristics
    console=False,                              # GUI app — no console window
    disable_windowed_traceback=False,
    icon=str(icon_path) if icon_path.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="DJ Tracks",
)
