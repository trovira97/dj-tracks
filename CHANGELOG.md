# Changelog

All notable changes to **DJ Tracks** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [Unreleased]

### Added — Audio quality and metadata pass
- **TrackInfo** carries full album-aware metadata: `album_artist`,
  `release_date` (full ISO), `track_number`, `disc_number`, `total_tracks`.
- **AudioMetadata** (reader) reads `album_artist` and `disc_n` too.
- **MP3 writer** now writes TRCK ("n/total"), TPOS, TPE2 (album artist),
  and uses the full release_date in TDRC.
- **FLAC writer** writes `albumartist`, `tracknumber`, `tracktotal`,
  `discnumber`.
- **M4A writer** writes `aART` (album artist), `trkn` ((n, total)), `disk`.
- **verify_and_fix** also checks `album_artist` and `track_number`.

### Changed — Maximum audio quality everywhere
- **yt-dlp `format_sort`** added: `["acodec:flac", "acodec:wav",
  "acodec:alac", "acodec:opus", "abr", "asr"]` — always selects the best
  available stream by codec then bitrate then sample rate.
- **YouTube fallback** now uses `ytmusicsearch1:` instead of `ytsearch1:`.
  YT Music streams are higher quality (opus 160 kbps vs YT's typical
  opus 128 / m4a 128) and search results are biased to official audio.
- **Default quality profile** is now "Máxima calidad (original)" — no
  re-encoding, keeps the source codec/bitrate intact (FLAC from Bandcamp,
  opus from YT Music, etc.).
- **Spotify cover** still 640×640 (max API serves) — full release_date
  + track/disc number + album artist now extracted.
- **Apple Music cover** bumped from 600×600 to **3000×3000bb** (max).
- **SoundCloud cover** bumped from `-t500x500` to `-original`
  (artist's source upload, no downscale).
- **Bandcamp cover** bumped from `_10` (350×350) to `_0` (typically
  1500×1500 original).
- **Cover size limit** raised from 10 MB → 20 MB so high-res Apple /
  Bandcamp artwork fits without being dropped.

### Added
- **Bandcamp provider**: search, URL resolution, and direct download
  (bypasses YouTube fallback). Uses the public `bcsearch_public_api`
  endpoint — no credentials required. Bandcamp results appear alongside
  Spotify / Apple Music / SoundCloud across the search, history,
  dashboard, and download panels.
- Bandcamp chip in the search filter row.
- Bandcamp filter in the history panel.
- Bandcamp bar in the dashboard platform breakdown.
- Bandcamp colour (`bc = #629AA9`) added to every theme.
- New `Platform.BANDCAMP` enum value + URL detection in `validators`.
- 12 new pytest tests for the Bandcamp provider (offline, mocked HTTP).
- 2 new tests covering Bandcamp URL detection in `detect_platform`.

### Changed
- `AudioDownloader` now treats Bandcamp the same way as SoundCloud:
  when the track has a `source_url`, hand it straight to yt-dlp instead
  of doing a YouTube text search. Means cleaner downloads with the
  original artist's audio.
- `subfolder_per_platform` setting now produces a `Bandcamp/` sub-folder
  too when enabled.
- Friendly error messages for common yt-dlp failures (403, 404, 429,
  age-restricted, geo-blocked, etc.) shown in the queue rows; full
  traceback still goes to logs.

### Fixed
- Toast crash on CustomTkinter >= 5.2: width/height moved from `.place()`
  to the widget constructor.

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
