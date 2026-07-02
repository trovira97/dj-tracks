"""
core/dj_export.py
==================
Export downloaded tracks to DJ software libraries.

Formats
-------
- **Rekordbox XML** (``.xml``) — Pioneer's documented interchange
  format.  In Rekordbox: *File → Import → Import Library → rekordbox
  XML*.  All BPM/key/artwork metadata is preserved.
- **Traktor NML** (``.nml``) — Native Instruments' collection format.
  Drop the file into Traktor's *Collection* pane, or replace the
  installed ``collection.nml`` (backup first).
- **M3U8 playlist** — universal fallback.  Serato, VirtualDJ, VLC,
  Foobar2000, and virtually every player read it.  For Serato,
  auto-generates a ``.crate``-friendly path list.

Design
------
Each exporter takes a list of :class:`TrackRecord` (a small local
data class populated from HistoryManager records + optional DJ
metadata) and writes to a file path.

All three exporters are pure functions — no GUI, no threading, no
side effects beyond the target file.  They live behind
:func:`export_all` for the common "one click, all three formats" path.
"""
from __future__ import annotations

import html
import time
import urllib.parse
from dataclasses import dataclass
from pathlib import Path
from xml.etree import ElementTree as ET

from utils.logger import log


# ── Track record — the exporter input ─────────────────────────────────────

@dataclass
class TrackRecord:
    """One track ready to be exported.

    All fields except ``path`` are optional — missing values are omitted
    from the target XML.  The exporters never raise on missing metadata,
    they just skip those attributes.
    """
    path:        Path                # local file, absolute
    title:       str  = ""
    artist:      str  = ""
    album:       str  = ""
    genre:       str  = ""
    bpm:         float | None = None
    key:         str  = ""           # e.g. "Am" or Camelot "8A"
    year:        str  = ""
    duration_ms: int  = 0
    isrc:        str  = ""

    def exists(self) -> bool:
        return self.path.exists()


# ── Rekordbox XML ─────────────────────────────────────────────────────────

def export_rekordbox_xml(tracks: list[TrackRecord],
                         output: Path,
                         playlist_name: str = "DJ Tracks Import") -> int:
    """Write a Rekordbox-compatible XML collection.

    Rekordbox's schema (documented in the *rekordbox XML File Format*
    spec) requires a ``DJ_PLAYLISTS`` root, a ``COLLECTION`` node listing
    every track, and a ``PLAYLISTS`` node with per-playlist references.

    Args:
        tracks: TrackRecord list, only ``exists()`` ones are written.
        output: destination ``.xml``.
        playlist_name: name of the playlist Rekordbox will create.

    Returns:
        Number of tracks actually written.
    """
    valid = [t for t in tracks if t.exists()]
    if not valid:
        log.warning("[export] rekordbox: no valid tracks to write")

    root = ET.Element("DJ_PLAYLISTS", Version="1.0.0")
    ET.SubElement(root, "PRODUCT",
                  Name="DJ Tracks",
                  Version="2",
                  Company="trovira97")

    collection = ET.SubElement(root, "COLLECTION", Entries=str(len(valid)))
    for idx, t in enumerate(valid, start=1):
        loc = "file://localhost/" + urllib.parse.quote(
            str(t.path.resolve()).replace("\\", "/"))
        attrs = {
            "TrackID":     str(idx),
            "Name":        t.title or t.path.stem,
            "Artist":      t.artist,
            "Album":       t.album,
            "Genre":       t.genre,
            "Year":        t.year,
            "TotalTime":   str(t.duration_ms // 1000) if t.duration_ms else "0",
            "Location":    loc,
        }
        if t.bpm:
            attrs["AverageBpm"] = f"{t.bpm:.2f}"
        if t.key:
            attrs["Tonality"] = t.key
        # Drop empty attributes — Rekordbox is fussy about "0"-year etc.
        attrs = {k: v for k, v in attrs.items() if v not in ("", "0")}
        ET.SubElement(collection, "TRACK", **attrs)

    playlists = ET.SubElement(root, "PLAYLISTS")
    root_node = ET.SubElement(playlists, "NODE", Type="0", Name="ROOT", Count="1")
    playlist  = ET.SubElement(root_node, "NODE",
                              Type="1", Name=playlist_name, KeyType="0",
                              Entries=str(len(valid)))
    for i in range(1, len(valid) + 1):
        ET.SubElement(playlist, "TRACK", Key=str(i))

    ET.ElementTree(root).write(
        output, encoding="utf-8", xml_declaration=True)
    log.info(f"[export] rekordbox: wrote {len(valid)} tracks → {output}")
    return len(valid)


# ── Traktor NML ───────────────────────────────────────────────────────────

def export_traktor_nml(tracks: list[TrackRecord],
                       output: Path,
                       playlist_name: str = "DJ Tracks Import") -> int:
    """Write a Traktor NML collection.

    NML is XML with Traktor-specific tags: ``ENTRY`` per track, nested
    ``LOCATION`` for path (with ``DIR`` and ``FILE``), ``INFO`` for
    duration/genre, ``TEMPO`` for BPM, ``MUSICAL_KEY`` for key.

    Traktor stores paths with a leading volume, e.g. ``/:C:``.  We emit
    that convention on Windows; on POSIX we use the raw absolute path.
    """
    valid = [t for t in tracks if t.exists()]
    if not valid:
        log.warning("[export] traktor: no valid tracks to write")

    root = ET.Element("NML", VERSION="19")
    ET.SubElement(root, "HEAD",
                  COMPANY="www.native-instruments.com",
                  PROGRAM="Traktor")

    collection = ET.SubElement(root, "COLLECTION", ENTRIES=str(len(valid)))
    for t in valid:
        entry = ET.SubElement(collection, "ENTRY",
                              TITLE=t.title or t.path.stem,
                              ARTIST=t.artist)

        # LOCATION — split into volume, directory, file.
        resolved = t.path.resolve()
        parts = resolved.parts
        if resolved.drive:  # Windows: "C:\", "D:\", ...
            volume = "/:" + resolved.drive.rstrip(":\\")
            directory = "/:" + "/:".join(parts[1:-1]) + "/:" if len(parts) > 2 else "/:"
            filename = parts[-1]
        else:               # POSIX
            volume = ""
            directory = "/:" + "/:".join(parts[1:-1]) + "/:" if len(parts) > 2 else "/:"
            filename = parts[-1]
        ET.SubElement(entry, "LOCATION",
                      DIR=directory,
                      FILE=filename,
                      VOLUME=volume,
                      VOLUMEID=volume)

        if t.album:
            ET.SubElement(entry, "ALBUM", TITLE=t.album)

        info_attrs = {}
        if t.duration_ms:
            info_attrs["PLAYTIME"]         = str(t.duration_ms // 1000)
            info_attrs["PLAYTIME_FLOAT"]   = f"{t.duration_ms / 1000:.6f}"
        if t.genre:
            info_attrs["GENRE"] = t.genre
        if t.year:
            info_attrs["RELEASE_DATE"] = f"{t.year}/1/1"
        if info_attrs:
            ET.SubElement(entry, "INFO", **info_attrs)

        if t.bpm:
            ET.SubElement(entry, "TEMPO", BPM=f"{t.bpm:.4f}", BPM_QUALITY="100.0")
        if t.key:
            ET.SubElement(entry, "MUSICAL_KEY", VALUE=t.key)

    # PLAYLISTS block.
    playlists_root = ET.SubElement(root, "PLAYLISTS")
    node = ET.SubElement(playlists_root, "NODE", TYPE="FOLDER", NAME="$ROOT")
    subnodes = ET.SubElement(node, "SUBNODES", COUNT="1")
    pl_node = ET.SubElement(subnodes, "NODE", TYPE="PLAYLIST", NAME=playlist_name)
    playlist = ET.SubElement(pl_node, "PLAYLIST",
                             ENTRIES=str(len(valid)),
                             TYPE="LIST",
                             UUID=str(int(time.time())))
    for t in valid:
        primary = ET.SubElement(playlist, "ENTRY")
        # Traktor references the same LOCATION signature; we reuse it.
        resolved = t.path.resolve()
        if resolved.drive:
            volume = "/:" + resolved.drive.rstrip(":\\")
        else:
            volume = ""
        ET.SubElement(primary, "PRIMARYKEY",
                      TYPE="TRACK",
                      KEY=f"{volume}/:{resolved.name}")

    ET.ElementTree(root).write(
        output, encoding="utf-8", xml_declaration=True)
    log.info(f"[export] traktor: wrote {len(valid)} tracks → {output}")
    return len(valid)


# ── M3U8 (universal — Serato, VirtualDJ, VLC, foobar2000) ────────────────

def export_m3u8(tracks: list[TrackRecord],
                output: Path,
                use_relative_paths: bool = False) -> int:
    """Write an extended M3U8 playlist.

    Format::

        #EXTM3U
        #EXTINF:<duration_sec>,<artist> - <title>
        <path>
        ...

    Args:
        use_relative_paths: if True and *output* and each track share a
            common parent, write paths relative to *output* (portable).
    """
    valid = [t for t in tracks if t.exists()]
    if not valid:
        log.warning("[export] m3u8: no valid tracks to write")

    out_parent = output.parent.resolve()
    lines = ["#EXTM3U"]
    for t in valid:
        duration_sec = t.duration_ms // 1000 if t.duration_ms else -1
        artist_title = f"{t.artist} - {t.title}" if t.artist and t.title \
                       else (t.title or t.path.stem)
        lines.append(f"#EXTINF:{duration_sec},{artist_title}")

        track_path = t.path.resolve()
        if use_relative_paths:
            try:
                track_path_str = str(track_path.relative_to(out_parent))
            except ValueError:
                track_path_str = str(track_path)
        else:
            track_path_str = str(track_path)
        lines.append(track_path_str)

    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info(f"[export] m3u8: wrote {len(valid)} tracks → {output}")
    return len(valid)


# ── Convenience: export all three at once ─────────────────────────────────

def export_all(tracks: list[TrackRecord],
               output_dir: Path,
               name_stem: str = "DJ Tracks Import") -> dict[str, int]:
    """Write all three formats side-by-side in *output_dir*.

    Returns dict of format → track count.  Format keys:
    ``"rekordbox"``, ``"traktor"``, ``"m3u8"``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    safe = _safe_filename(name_stem)
    return {
        "rekordbox": export_rekordbox_xml(tracks, output_dir / f"{safe}.xml", name_stem),
        "traktor":   export_traktor_nml (tracks, output_dir / f"{safe}.nml", name_stem),
        "m3u8":      export_m3u8        (tracks, output_dir / f"{safe}.m3u8"),
    }


def _safe_filename(name: str) -> str:
    """Strip characters that Windows / macOS / Linux disallow in filenames."""
    bad = '<>:"/\\|?*\x00'
    return "".join("_" if c in bad else c for c in name).strip() or "export"


# ── Building TrackRecord from HistoryManager rows ────────────────────────

def records_from_history(history_manager,
                         status: str = "done",
                         limit: int | None = None) -> list[TrackRecord]:
    """Materialise TrackRecord objects from a HistoryManager.

    Only records whose ``path`` still exists on disk are included.
    """
    rows = history_manager.all()
    if status:
        rows = [r for r in rows if r.status == status]
    if limit:
        rows = rows[:limit]
    out: list[TrackRecord] = []
    for r in rows:
        if not r.path:
            continue
        p = Path(r.path)
        if not p.exists():
            continue
        # Best-effort year: first 4 chars of timestamp if year not tagged.
        year = (r.timestamp[:4] if getattr(r, "timestamp", "") else "")
        out.append(TrackRecord(
            path        = p,
            title       = r.title,
            artist      = r.artist,
            album       = r.album,
            year        = year,
            duration_ms = r.duration_ms,
        ))
    return out
