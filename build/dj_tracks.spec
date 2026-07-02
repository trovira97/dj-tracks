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
  - spotdl + spotipy (runtime engine for Spotify / Apple Music)

Build with:
    py -m PyInstaller --noconfirm --clean build/dj_tracks.spec
"""
import sys
from pathlib import Path
from PyInstaller.utils.hooks import collect_data_files, collect_submodules, collect_all

ROOT = Path(SPECPATH).parent
IS_WINDOWS = sys.platform.startswith("win")
IS_MAC     = sys.platform == "darwin"

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

# ── spotdl — now a runtime dependency (dual-engine downloader) ───────────────
# Since commit 616bea5 the downloader imports spotdl at runtime as the
# preferred engine for Spotify / Apple Music tracks.  collect_all pulls in
# the package, its templates, and every submodule the dynamic import
# machinery would otherwise miss.
_sd_datas, _sd_binaries, _sd_hidden = [], [], []
try:
    _sd_datas, _sd_binaries, _sd_hidden = collect_all("spotdl")
except Exception:
    pass

# ── Bundled data ──────────────────────────────────────────────────────────────
datas = []
datas += collect_data_files("customtkinter")
datas += _tls_datas
datas += _sd_datas

# ffmpeg goes to the bundle root so audio_downloader._find_ffmpeg picks it up.
# On Windows we bundle ffmpeg.exe directly.  On macOS/Linux we assume
# the user has ffmpeg installed via Homebrew / apt / dnf — the downloader
# falls back to shutil.which("ffmpeg") if the bundled binary is absent.
if IS_WINDOWS and (ROOT / "ffmpeg.exe").exists():
    datas.append((str(ROOT / "ffmpeg.exe"), "."))
elif (ROOT / "ffmpeg").exists() and not IS_WINDOWS:
    datas.append((str(ROOT / "ffmpeg"), "."))

# Icons and logos.
if (ROOT / "assets").exists():
    datas.append((str(ROOT / "assets"), "assets"))

# ── Binaries (native shared libraries) ───────────────────────────────────────
binaries = []
binaries += _tls_binaries
binaries += _sd_binaries

# ── Hidden imports ────────────────────────────────────────────────────────────
hiddenimports = []
hiddenimports += collect_submodules("mutagen")
hiddenimports += collect_submodules("spotipy")   # spotdl's Spotify Web API client
hiddenimports += _tls_hidden
hiddenimports += _sd_hidden
hiddenimports += [
    "PIL._tkinter_finder",
    "PIL.ImageTk",
    "pygame",
    "pygame.mixer",
]

# ── Modules to leave out (huge & unused at runtime) ───────────────────────────
# spotdl is NOT excluded any more — see the collect_all("spotdl") call above.
excludes = [
    "pytest",
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

# Icon: .ico on Windows, .icns on macOS, .png as universal fallback.
if IS_WINDOWS:
    icon_path = ROOT / "assets" / "icon.ico"
elif IS_MAC:
    icon_path = ROOT / "assets" / "icon.icns"
else:
    icon_path = ROOT / "assets" / "icon.png"

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

# macOS: wrap the bundle in a proper .app.
if IS_MAC:
    app = BUNDLE(
        coll,
        name="DJ Tracks.app",
        icon=str(icon_path) if icon_path.exists() else None,
        bundle_identifier="com.trovira97.djtracks",
        info_plist={
            "CFBundleShortVersionString": "2.2.0",
            "NSHighResolutionCapable": True,
            "LSMinimumSystemVersion": "11.0",
        },
    )
