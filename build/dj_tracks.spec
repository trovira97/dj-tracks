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
  - tls_client native DLL (spotdl dep — must be collected explicitly)

Build with:
    py -m PyInstaller --noconfirm --clean build/dj_tracks.spec
"""
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

ROOT = Path(SPECPATH).parent

# ── tls_client — native DLL must be bundled explicitly ───────────────────────
# spotdl installs tls_client, which carries a native DLL
# (tls-client-64.dll on Windows).  PyInstaller bundles the .py files but
# misses the DLL unless we call collect_all here.  Without this, the app
# crashes on any machine where spotdl is not installed at the system level.
_tls_datas, _tls_binaries, _tls_hidden = [], [], []
try:
    _tls_datas, _tls_binaries, _tls_hidden = collect_all("tls_client")
except Exception:
    pass  # tls_client not present in this build env — safe to skip

# ── Bundled data ──────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files("customtkinter")
datas += _tls_datas

# ffmpeg goes to the bundle root so audio_downloader._find_ffmpeg picks it up.
if (ROOT / "ffmpeg.exe").exists():
    datas.append((str(ROOT / "ffmpeg.exe"), "."))

# Icons and logos.
if (ROOT / "assets").exists():
    datas.append((str(ROOT / "assets"), "assets"))

# ── Binaries (native shared libraries) ───────────────────────────────────────
binaries = []
binaries += _tls_binaries

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = []
hiddenimports += collect_submodules("mutagen")
hiddenimports += _tls_hidden
hiddenimports += [
    "PIL._tkinter_finder",
    "PIL.ImageTk",
]

# ── Modules to leave out (huge & unused at runtime) ───────────────────────────
excludes = [
    "pytest",
    "spotdl",          # Python package not imported; only its ffmpeg path is checked on disk
    "tests",
    "matplotlib",
    "numpy.tests",
    "pandas",
]

# ── Analysis ──────────────────────────────────────────────────────────────────
a = Analysis(
    [str(ROOT / "main.py")],
    pathex=[str(ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    # Register the vendored yt_dlp hook dir so that if the system-installed
    # yt_dlp is absent or a different version, the bundled hook still fires.
    hookspath=[str(ROOT / ".vendor" / "yt_dlp" / "__pyinstaller")],
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
