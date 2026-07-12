# Changelog

All notable changes to **DJ Tracks** are documented here.
Format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
this project adheres to [Semantic Versioning](https://semver.org/).

---

## [Unreleased]

## [2.3.2] — 2026-07-12

### Added
- **"Solo los que faltan" button** — when a pasted playlist has some
  tracks already in your library, a new one-click action next to
  "Seleccionar todo" ticks exactly the missing ones so you don't have
  to hand-uncheck the duplicates.  Shown only when relevant.

### Changed
- **Library dedup rebuild off the UI thread** — after each successful
  download the index rebuild now runs in a background thread instead
  of blocking Tk, eliminating the ~40 ms hiccup that was visible in
  multi-track batches.
- **Repo housekeeping** — reorganized Discord server-maintenance
  scripts under `scripts/discord/`, removed a stale VBS launcher
  with a hardcoded runtime path, removed the deprecated
  `providers/base_provider.py` re-export module, dead-code sweep
  (5 unused public functions, ~40 LOC), shared `BROWSER_USER_AGENT`
  constant across the HTTP providers.
- **Controller slim-down** — extracted `AppController.update_ytdlp`
  (89 lines) into `utils/ytdlp_updater.py`; controller shrank from
  730 to 651 lines (-11%).

### Fixed
- **404s no longer kill the download** — a SoundCloud 404 (track
  removed / DMCA / never existed on SC) used to leave the row in a
  permanent "No se encontró el contenido" error state.  It now
  triggers the cross-platform retry, which searches the same track
  on YouTube / Apple Music / Bandcamp automatically.
- **Bandcamp bot-protection** — Bandcamp's public search API started
  returning HTML challenge pages (Cloudflare), which the provider was
  blindly parsing as JSON and spamming
  `Expecting value: line 1 column 1 (char 0)` errors on every search.
  Now detects the HTML content-type upfront, disables Bandcamp for
  the session with a single warning, and returns clean empty results.

### Tests
- Went from 130 → 294 tests (+126 %).  New coverage for
  `app_updater` (semver + asset picking), `search_manager` (dedup +
  URL routing), `donor_gate` (full freemium logic including offline
  grace), `ytdlp_updater` (version normalisation + status paths),
  `audio_downloader` (7 error classifiers, `_humanise_error`,
  `_build_yt_query`, `DownloadTask`), `controller`
  (`_process_task`, `_try_cross_platform_retry`, `_dedup_check`,
  `_post_process`, `_dj_enrich`).  The O.B.I. 404 bug that started
  the retry-classifier fix now has 10 regression tests around it.

## [2.3.1] — 2026-07-12

### Fixed
- **Traktor NML playlist** — `PRIMARYKEY.KEY` was truncated to
  `/:VOLUME/:FILE`, causing every track in the exported playlist to
  appear as *missing* on import.  Now emits the full
  `/:VOL/:DIR/:.../:FILE` signature that matches the `LOCATION`
  element in the collection, so Traktor resolves the tracks correctly.
- **Weekly digest** (backend) — the "sin match" headline undercounted
  when more than 5 distinct unmatched questions existed in a week
  (only the top-5 grouped rows were summed).  The count now reflects
  the full long tail.

### Chore
- CI green again — ran `ruff --fix` across the new modules introduced
  in 2.3.0 (17 style findings auto-resolved).

## [2.3.0] — 2026-07-06

### Added
- **DJ software export** — one click writes your download history to
  Rekordbox XML + Traktor NML + M3U8 playlist side-by-side.  Import
  directly into Rekordbox (*File → Import Library*) or Traktor (drop
  the .nml into Collection).  The M3U8 works with Serato, VirtualDJ,
  VLC and every other player.  Button "DJ" in the History panel.
- **Playlist library dedup** — when you paste a playlist URL,
  the search bar surfaces "✓ N ya lo tienes" so you can see at a
  glance how much of a big playlist is new vs already downloaded.
  Backed by a fast in-memory index rebuilt from the download history
  (accent/feat/remix aware — "Artist (feat. X)" matches "Artist").
- **macOS + Linux builds** — GitHub Actions release workflow now
  builds a `.dmg` for macOS (universal2) and a `.tar.gz` for Linux
  alongside the Windows `.zip`.  Same tag triggers all three; each
  runs on its own OS runner via a spec that adapts to the platform
  (bundles `ffmpeg.exe` only on Windows, produces a `.app` bundle
  on macOS, expects `apt install ffmpeg` on Linux).
- **Community analytics on the bot side** — weekly digest posted to
  `#🛡️-mod-chat` every Monday 10:00 UTC with member/donation/FAQ
  stats + top unmatched questions worth turning into new FAQ entries.
- **Backend health monitor** — bot pings the FastAPI health endpoint
  every 5 min; DMs the owner after 3 consecutive misses and again
  when the service recovers.
- **Milestone role bridge** — piggybacks on Koya's level-up
  announcements to assign `@Miembro Activo` / `@Regular` /
  `@Veterano` / `@Leyenda` at levels 5 / 20 / 50 / 100.  Removes
  lower tiers per the single-tier policy.  Free-tier alternative to
  Koya's role rewards (which require Premium).

### Architecture
- Project-wide audit, MIT license added, this changelog brought up to date.
- `CONTRIBUTING.md` documenting how to work on the codebase.

### UI / UX
- New **Logs** panel in the sidebar: live, colour-coded view of the
  app's logger with level filter, copy-to-clipboard and "open logs
  folder" buttons.  Replaces the need to keep an external terminal
  open while using the app.
- **Mandatory Discord login** on first launch (DarkBot-style): the
  app blocks the main UI until the user OAuth-links their Discord
  account or quits.  Pre-linking everyone means donations later
  don't need an OAuth step at all.

### Backend
- Live Discord role check with cache fallback in `/usage/check`,
  `/usage/record` and `/usage/link` — when an admin manually grants
  the Donor role in Discord, the user's app unlocks automatically
  on the next request, no webhook required.
- Bot `on_member_update` listener mirrors Discord role changes
  into the donors table in real time and DMs the recipient a
  congratulatory message.

---

## [2.1.0] — 2026-06-22 — First public release

### Added — Discord bot + donor flow
- Persistent Discord bot (`backend/bot.py`) running alongside FastAPI
  on the same Fly machine.  Three DM commands inspired by DarkBot:
  - `!donate <amount>` — replies with an embed containing a
    pre-filled Ko-fi URL and the donor's own Discord ID in a code
    block, ready to paste into the Ko-fi message field.
  - `!fixrole` — re-assigns the Donor role to users in our database
    who lost it (left + rejoined the server, manual removal, etc.).
  - `!help` — lists available commands.

### Added — Server-authoritative freemium gate
- New `usage` table keyed by `device_id` (UUID generated on first
  run); the download counter lives on the backend so editing
  `usage.json` locally doesn't reset it.
- `POST /usage/check` returns `{allowed, remaining, is_donor}` based
  on the server count; `/usage/record` bumps it; `/usage/link` binds
  device → discord_id after OAuth.
- Local client (`utils/donor_gate.py`) caches the verdict for 60 s
  and falls back to a 24-hour offline shadow counter if the server
  is unreachable, so a network blip doesn't lock the app.

### Added — Ko-fi automated donor matching
- `POST /kofi-webhook` with three matching paths in order:
  1. Discord User ID embedded in the donation message → role
     assigned via the Discord REST API instantly.
  2. Email already linked from a prior OAuth → role assigned.
  3. Otherwise stash in `pending_donations`; the next OAuth claims it
     by Discord-registered email (we ask for the `email` scope).
- Donor records survive container restarts via a persistent Fly volume.

### Added — Beatport as primary metadata source
- `metadata/beatport.py` scrapes Beatport's public `__NEXT_DATA__`
  React-Query cache (no API key needed) and parses tracks into
  `{title, mix, artists, remixers, bpm, key, camelot, genre,
  publisher, year, isrc}`.
- Camelot lookup that accepts both sharp and flat spellings
  (`Bb Minor`, `A# Minor`, `Ab Minor`).
- Fuzzy match via rapidfuzz with a 70-point floor and a soft artist
  overlap gate.
- On-disk cache (`<user_cache_dir>/DJ Tracks/beatport.json`):
  positive results forever, negatives 7 days.  Cold lookup ~1.8 s,
  warm lookup ~0 ms.
- `enrich_files()` now runs Beatport → GetSongBPM → librosa.
- `HistoryRow` gains a colour-coded source badge
  (`BEATPORT` mint / `DB` muted / `LOCAL` dim).

### Added — YouTube as a first-class platform
- `providers/youtube_provider.py` resolves any YouTube URL (single
  video or playlist) into `TrackInfo` via yt-dlp's metadata
  extraction; text search uses `ytsearchN:` so no API key is needed.
- Best-effort `Artist - Title` split with `- Topic` channel
  cleanup; falls back to uploader when the title has no
  separator.
- `utils.validators` recognises `youtube.com`, `youtu.be` and
  `music.youtube.com`; `Platform.YOUTUBE` joins the direct-URL
  fast path so pasted links download immediately.

### Added — Apple Music-style player
- Persistent mini-player bar above the status bar with cover art,
  scrubber, prev/next, volume, and an expanded "Now Playing"
  window on cover click.
- Queue derived from the current history page so prev/next walks
  the visible list.
- Auto-advance when a track ends and there's another queued.
- Cover art read from embedded ID3 (APIC), MP4 (covr) and Vorbis
  pictures; cached by raw-byte identity so state-change events
  don't re-decode the image.

### Added — Auto-update via GitHub Releases
- `utils/app_updater.py` queries `api.github.com/repos/<repo>/
  releases/latest`, compares semantic versions, and either swaps a
  single `.exe` (PyInstaller `--onefile`) or extracts a `.zip`
  bundle (`--onedir`) via a detached `robocopy /MIR` that takes
  over after the running process exits.
- Background check on startup with a toast notification when an
  update is available.

### Fixed — Broadened DRM detection
- `is_drm_error` now catches the real-world SoundCloud failures
  ("not currently available", "sign in to download", HLS+AES 403)
  in addition to the literal "drm" keyword.
- Classification operates on the **raw** yt-dlp error
  (`task.error_raw`); the humanised Spanish message is no longer
  the source of truth for the cross-platform retry decision.

### Fixed — Geo-block retry never fired
- `is_geo_error` was checking `"geo" in msg` against the humanised
  Spanish message ("Bloqueado en tu región") and never matched.
- Same brittleness fixed for age / private / premium classes.

---

## [Older history — pre v2.1.0]

### Audio quality and metadata pass
- `TrackInfo` carries full album-aware metadata: `album_artist`,
  `release_date` (full ISO), `track_number`, `disc_number`,
  `total_tracks`.
- MP3 writer: TRCK ("n/total"), TPOS, TPE2 (album artist), full
  release_date in TDRC.  FLAC writer: `albumartist`,
  `tracknumber`, `tracktotal`, `discnumber`.  M4A writer: `aART`,
  `trkn` ((n, total)), `disk`.
- yt-dlp `format_sort`: `["acodec:flac", "acodec:wav",
  "acodec:alac", "abr", "asr"]` — always picks the best stream by
  codec then bitrate then sample rate.
- YouTube fallback uses `ytmusicsearch1:` instead of `ytsearch1:`
  for higher-quality streams biased to official audio.
- Default quality profile: "Máxima calidad (original)" — no
  re-encoding, keeps the source codec/bitrate intact.

### DJ tooling
- `metadata/dj_metadata.py` enrichment pipeline: GetSongBPM →
  librosa fallback (kept as path 2 and 3 after Beatport).
- Camelot wheel mapping, ReplayGain via ffmpeg ebur128, optional
  acoustic-fingerprint deduplication and DJ filename renaming
  (`Artist - Title [BPM - Camelot].ext`).
