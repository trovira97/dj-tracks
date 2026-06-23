# Contributing to DJ Tracks

Thanks for thinking about helping!  This is a personal project but
contributions of all kinds are welcome — bug reports, ideas, code, or
just feedback in [Discord](https://discord.gg/cNkh8Yd2A7).

## Quick start

```bash
git clone https://github.com/trovira97/dj-tracks
cd dj-tracks

# Optional but recommended: virtualenv
python -m venv .venv
.venv\Scripts\activate                       # Windows
# source .venv/bin/activate                  # macOS / Linux

python -m pip install -r requirements.txt
python main.py                               # source mode
python -m pytest tests/ -q                   # 117 tests should pass
```

Need `ffmpeg.exe` on the `PATH` or in the project root for audio
conversion and ReplayGain.  Spotify needs a Client ID + Secret in
**Ajustes** — full walkthrough in [README.md](./README.md).

## Code style

- **Type hints everywhere** in new code (`from __future__ import
  annotations` for forward refs).
- **Docstrings on public functions and classes** explaining *why*,
  not just *what*.
- **Logging, not `print`**.  Use the module logger:
  `log = logging.getLogger("dj_tracks.<module>")`.  Anything you emit
  shows up live in the in-app Logs panel.
- **No new top-level dependencies without a clear win** — every
  extra wheel adds size + cold-start time + a future maintenance
  liability.
- **Line length ~100** is a soft target — don't sacrifice
  readability for it.
- **No emojis in code or commit messages**, please — only in
  user-facing strings where they communicate meaning.

## Repo layout

```
main.py                  # entry point: bootstrap + AppController + GUI
__version__.py           # single source of truth for the version string

core/
  controller.py          # AppController — orchestrates queue, downloads,
                         #   post-processing, DJ enrichment, retries
  search_manager.py      # fan-out search across providers

providers/
  spotify_provider.py    # SpotifyProvider (spotipy)
  applemusic_provider.py # AppleMusicProvider (iTunes Search API)
  soundcloud_provider.py # SoundCloudProvider (public client_id)
  bandcamp_provider.py   # BandcampProvider (bcsearch_public_api)
  youtube_provider.py    # YouTubeProvider (yt-dlp metadata)

downloader/
  audio_downloader.py    # yt-dlp + spotdl wrapper, error classification,
                         #   cookies-from-browser auth
  quality_manager.py     # QualityProfile presets

metadata/
  beatport.py            # primary BPM/key/Camelot/genre source (scrape)
  dj_metadata.py         # enrichment pipeline (Beatport → GetSongBPM →
                         #   librosa), ReplayGain, DJ rename
  metadata_writer.py     # mutagen ID3 / Vorbis / MP4
  metadata_reader.py     # ditto, read side

utils/
  app_updater.py         # GitHub Releases auto-update
  audio_player.py        # pygame mixer singleton + queue
  donor_gate.py          # local cache for the server-authoritative
                         #   freemium counter
  donor_client.py        # HTTP client for the backend
  history_manager.py     # persisted download history
  paths.py               # platform-aware data / config / logs dirs
  win_native.py          # silent subprocess + AppUserModelID
  validators.py          # URL platform detection
  shortcut.py            # desktop shortcut creator
  notifications.py       # native system notifications
  logger.py              # root logger configuration
  single_instance.py     # single-instance lock

ui/
  gui.py                 # CustomTkinter UI — entire interface
  donations.py           # donation dialog

backend/                 # FastAPI service on Fly.io
  app.py                 # HTTP endpoints (verify, OAuth, Ko-fi webhook,
                         #   usage gate)
  bot.py                 # Discord bot (gateway, !donate, !fixrole,
                         #   on_member_update)
  Dockerfile             # production image
  fly.toml               # Fly.io config

tests/                   # pytest suite (currently 117 tests on validators)

build/
  dj_tracks.spec         # PyInstaller spec
  build.bat              # one-click build script
```

## Tests

```bash
python -m pytest tests/ -q
```

When adding code that has clear inputs and outputs (URL detection,
metadata parsing, error classification, etc.), add a test for it.
The validators suite is the model — small, deterministic, fast.

## Reporting bugs

Open an issue with:
1. **What you did** — minimal steps to reproduce.
2. **What you expected** vs **what happened**.
3. **App version** (Ajustes → "Buscar actualizaciones" header) and
   **OS**.
4. **Logs**: in-app **LOGS** panel → "Copiar todo" → paste in the
   issue.  No sensitive info, but if you're worried, redact your
   downloads folder path.

## Backend / Discord / Ko-fi infra

The freemium gate and donor flow lean on three external services
(Discord OAuth + bot, Ko-fi webhooks, Fly.io hosting).  All the
secrets live in `backend/.env` (gitignored) and Fly secrets.
**Do not** commit anything that looks like a token, secret, key, or
ID with more than 12 random characters.

## Pull requests

- Branch off `main`.
- One change per PR — a feature, a fix, a refactor.  Don't bundle.
- The bar is "would I review this in 5 minutes and ship it?"
- Commit messages: short imperative subject (≤72 chars), body
  paragraphs separated by blank lines, no trailing period.

## License

MIT — see [LICENSE](./LICENSE).  By contributing you agree your
contribution is licensed under the same.
