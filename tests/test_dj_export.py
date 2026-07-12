"""Tests for the DJ software export module."""
from __future__ import annotations

from pathlib import Path
from xml.etree import ElementTree as ET

import pytest

from core.dj_export import (
    TrackRecord,
    export_all,
    export_m3u8,
    export_rekordbox_xml,
    export_traktor_nml,
)


@pytest.fixture
def sample_tracks(tmp_path):
    """Two real files on disk so ``exists()`` checks pass."""
    a = tmp_path / "artist_a - track_1.mp3"
    b = tmp_path / "artist_b - track_2.mp3"
    a.write_bytes(b"\x00")
    b.write_bytes(b"\x00")
    return [
        TrackRecord(
            path=a, title="Track 1", artist="Artist A", album="Album 1",
            genre="House", bpm=128.0, key="8A", year="2024", duration_ms=210_000,
        ),
        TrackRecord(
            path=b, title="Track 2", artist="Artist B", album="Album 2",
            genre="Techno", bpm=136.5, key="1B", year="2023", duration_ms=185_000,
        ),
    ]


# ── Rekordbox XML ─────────────────────────────────────────────────────────

def test_rekordbox_xml_valid_structure(sample_tracks, tmp_path):
    out = tmp_path / "col.xml"
    n = export_rekordbox_xml(sample_tracks, out, playlist_name="Test PL")
    assert n == 2

    tree = ET.parse(out)
    root = tree.getroot()
    assert root.tag == "DJ_PLAYLISTS"

    collection = root.find("COLLECTION")
    assert collection is not None
    assert collection.get("Entries") == "2"

    tracks = collection.findall("TRACK")
    assert len(tracks) == 2
    assert tracks[0].get("Name")   == "Track 1"
    assert tracks[0].get("Artist") == "Artist A"
    assert tracks[0].get("AverageBpm") == "128.00"
    assert tracks[0].get("Tonality")   == "8A"
    assert tracks[0].get("Location", "").startswith("file://localhost/")

    playlists = root.find("PLAYLISTS")
    playlist_node = playlists.find(".//NODE[@Name='Test PL']")
    assert playlist_node is not None
    assert playlist_node.get("Entries") == "2"


def test_rekordbox_skips_missing_files(tmp_path):
    ghost = TrackRecord(path=tmp_path / "doesnt-exist.mp3",
                        title="X", artist="Y")
    n = export_rekordbox_xml([ghost], tmp_path / "col.xml")
    assert n == 0


# ── Traktor NML ───────────────────────────────────────────────────────────

def test_traktor_nml_valid_structure(sample_tracks, tmp_path):
    out = tmp_path / "col.nml"
    n = export_traktor_nml(sample_tracks, out, playlist_name="Test PL")
    assert n == 2

    root = ET.parse(out).getroot()
    assert root.tag == "NML"
    assert root.get("VERSION") == "19"

    collection = root.find("COLLECTION")
    assert collection is not None
    assert collection.get("ENTRIES") == "2"

    entries = collection.findall("ENTRY")
    assert entries[0].get("TITLE")  == "Track 1"
    assert entries[0].get("ARTIST") == "Artist A"

    tempo = entries[0].find("TEMPO")
    assert tempo is not None
    assert float(tempo.get("BPM")) == pytest.approx(128.0)

    key = entries[0].find("MUSICAL_KEY")
    assert key.get("VALUE") == "8A"


def test_traktor_playlist_key_matches_full_location(sample_tracks, tmp_path):
    """Playlist PRIMARYKEY.KEY must reference the full LOCATION path,
    not just volume+filename — otherwise Traktor shows the tracks as
    missing when importing the playlist."""
    out = tmp_path / "col.nml"
    export_traktor_nml(sample_tracks, out)

    root = ET.parse(out).getroot()
    primary_keys = [p.get("KEY") for p in root.findall(".//PRIMARYKEY")]
    assert len(primary_keys) == 2
    # KEY must contain the full path segments — a bare "/:C/:file.mp3"
    # would mean Traktor can't relocate the tracks.
    for k in primary_keys:
        assert k.count("/:") >= 3, (
            f"PRIMARYKEY.KEY looks truncated (no directory): {k}"
        )


# ── M3U8 ──────────────────────────────────────────────────────────────────

def test_m3u8_extended_format(sample_tracks, tmp_path):
    out = tmp_path / "list.m3u8"
    n = export_m3u8(sample_tracks, out)
    assert n == 2

    lines = out.read_text(encoding="utf-8").strip().splitlines()
    assert lines[0] == "#EXTM3U"
    assert lines[1] == "#EXTINF:210,Artist A - Track 1"
    assert Path(lines[2]).name == "artist_a - track_1.mp3"
    assert lines[3] == "#EXTINF:185,Artist B - Track 2"


def test_m3u8_relative_paths(sample_tracks, tmp_path):
    out = tmp_path / "list.m3u8"
    export_m3u8(sample_tracks, out, use_relative_paths=True)
    lines = out.read_text(encoding="utf-8").splitlines()
    # Relative to tmp_path — should be just the filename.
    assert lines[2] == "artist_a - track_1.mp3"


# ── export_all convenience ────────────────────────────────────────────────

def test_export_all_produces_three_files(sample_tracks, tmp_path):
    out = tmp_path / "exports"
    counts = export_all(sample_tracks, out, name_stem="My Set")
    assert counts == {"rekordbox": 2, "traktor": 2, "m3u8": 2}
    assert (out / "My Set.xml").exists()
    assert (out / "My Set.nml").exists()
    assert (out / "My Set.m3u8").exists()


def test_safe_filename_strips_bad_chars(sample_tracks, tmp_path):
    counts = export_all(sample_tracks, tmp_path, name_stem='bad<>:"/\\|?*name')
    assert counts["rekordbox"] == 2
    # The output files should exist under a sanitised name.
    xmls = list(tmp_path.glob("*.xml"))
    assert len(xmls) == 1
    assert "<" not in xmls[0].name and "|" not in xmls[0].name
