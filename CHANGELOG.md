# Changelog

All notable changes to **DJ Tracks** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added
- **Standalone installer build pipeline** (`build/`):
  - PyInstaller spec bundling ffmpeg, assets, and CustomTkinter data.
  - Inno Setup installer script — per-user install, no admin required.
  - One-click `build.bat` that runs the full pipeline.
  - Full build README with troubleshooting.
- `utils/paths.py` — central resolver for runtime data paths. In source
  mode keeps the existing layout; in frozen mode (PyInstaller bundle)
  redirects config / history / queue / logs to `%APPDATA%/DjTracks/`.

### Changed
- `logger`, `controller`, `history_manager`, and `queue_persistence` now
  resolve their paths via `utils.paths` so installed and source modes
  both work correctly.
- `main.py` skips the runtime pip bootstrap when running from a frozen
  bundle (all deps are already inside).
- GUI icon and ffmpeg lookup use `bundled_resource()` so they work both
  in source mode and when extracted from the PyInstaller bundle.

## [2.1.0] — 2026-06-01

### Added
- **Queue persistence**: pending downloads are saved on close and re-enqueued
  on next launch (`config/queue.json`).
- **History row actions**: double-click opens the file in the file manager;
  right-click shows a context menu (open file, open folder, copy path).
- **Track context menu**: right-click any search result to open it on its
  source platform, copy the link, or copy the title.
- **Double-click on download queue row**: opens the completed file.
- **Environment-variable credentials**: `SPOTIFY_CLIENT_ID`,
  `SPOTIFY_CLIENT_SECRET`, `SOUNDCLOUD_CLIENT_ID`, `APPLE_MUSIC_API_KEY`
  override values in `settings.json`.
- **Vinyl record icon** generated programmatically with PIL
  (`assets/icon.ico` + `assets/logo.png`).
- **Test suite** with pytest (`tests/`): validators, file utils, quality
  manager, providers, history, queue persistence.
- **`pyproject.toml`**: modern packaging configuration.
- **Central version constant** (`__version__.py`).
- **`CHANGELOG.md`**.
- **More keyboard shortcuts**: Ctrl+D (Downloads), Ctrl+H (History),
  Ctrl+Q (Quit).

### Changed
- **Concurrent downloads** via `ThreadPoolExecutor` (config `threads`, default 2).
- **Concurrent search** across providers via `ThreadPoolExecutor`.
- Vinyl icon replaces the placeholder app icon.
- Sidebar version reads from the central `__version__` constant.

### Fixed
- `AudioMetadata.artists` used mutable default `None` instead of
  `field(default_factory=list)`.
- Download cancellation now actually aborts active downloads via the
  yt-dlp progress hook (previously the flag was set but never read).
- Theme change rebuilds all panels so colours apply immediately.
- Status bar updates after saving Settings.
- Toast positioning is clamped to stay on-screen.
- `get_unique_path()` has a 9 999 iteration cap with UUID fallback.
- Windows reserved filenames (`CON`, `NUL`, `COM1`…) are prefixed with `_`.
- Cover-art download validates `Content-Type` and rejects responses > 10 MB.
- LRU-bounded cover cache (300 entries) replaces the unbounded dict.
- `HistoryManager` is now thread-safe with snapshot-based persistence.
- `_save()` no longer silences errors — logs `PermissionError` / `OSError`.

### Security
- `config/settings.json`, `config/history.json`, and `config/queue.json`
  are now all in `.gitignore`.
- Python 3.9+ version guard in `main.py` with a clear error message.

## [2.0.0] — Prior

Initial multi-platform release with serial download worker.
