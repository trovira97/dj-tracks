"""Tests for ``metadata.metadata_reader``.

The reader is the counterpart to ``metadata_writer``: it feeds
``verify_and_fix`` (already tested) and the DJ-enrichment pipeline.
Tests mock Mutagen so we don't need real audio fixtures.

Focus:
- ``AudioMetadata.artist_str`` — comma-joined artists property
- ``read_metadata`` mapping: title/artist/album/year/genre/isrc
- Track/disc number parsing incl. the ``"n/total"`` format
- Fallbacks: 'artist' vs 'artists', 'date' vs 'year'
- Duration + bitrate extraction from ``audio.info``
- Cover extraction from the full-tags interface (both ``.data`` and
  ``.value`` bytes attributes)
- Failure paths: File returns None, Mutagen raises, cover extraction
  throws inside the try/except
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from metadata.metadata_reader import AudioMetadata, read_metadata


# ─────────────────────────────────────────────────────────────────────────
# AudioMetadata.artist_str
# ─────────────────────────────────────────────────────────────────────────

def test_artist_str_joins_multiple():
    m = AudioMetadata(artists=["Daft Punk", "Pharrell Williams"])
    assert m.artist_str == "Daft Punk, Pharrell Williams"


def test_artist_str_single_artist():
    assert AudioMetadata(artists=["A"]).artist_str == "A"


def test_artist_str_empty_list():
    assert AudioMetadata().artist_str == ""


# ─────────────────────────────────────────────────────────────────────────
# read_metadata — happy paths
# ─────────────────────────────────────────────────────────────────────────

def _mock_audio(tags: dict, *, duration=210.0, bitrate=320_000):
    """Build a mocked Mutagen easy-audio object."""
    audio = MagicMock()

    def get(key, default=None):
        return tags.get(key, default)
    audio.get.side_effect = get
    audio.__getitem__ = MagicMock(side_effect=lambda k: tags[k])

    info = MagicMock()
    info.length  = duration
    info.bitrate = bitrate
    audio.info   = info
    return audio


def test_read_metadata_full_shape(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    tags = {
        "title":       ["Get Lucky"],
        "artist":      ["Daft Punk"],
        "album":       ["RAM"],
        "albumartist": ["Daft Punk"],
        "date":        ["2013-05-17"],
        "genre":       ["Electronic"],
        "isrc":        ["USQX91300224"],
        "tracknumber": ["8/13"],
        "discnumber":  ["1/2"],
    }
    audio = _mock_audio(tags)
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)

    assert meta is not None
    assert meta.title        == "Get Lucky"
    assert meta.artists      == ["Daft Punk"]
    assert meta.album        == "RAM"
    assert meta.album_artist == "Daft Punk"
    assert meta.year         == "2013"          # first 4 chars of date
    assert meta.genre        == "Electronic"
    assert meta.isrc         == "USQX91300224"
    assert meta.track_n      == 8               # 'n/total' → n
    assert meta.disc_n       == 1
    assert meta.duration     == 210.0
    assert meta.bitrate      == 320              # kbps (raw was 320_000)


def test_read_metadata_falls_back_from_date_to_year(tmp_path):
    """FLAC uses 'date'; some legacy MP3s use 'year'.  The reader
    should try 'date' first, then 'year'."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"year": ["2015"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.year == "2015"


def test_read_metadata_falls_back_from_artist_to_artists(tmp_path):
    """Some formats use plural 'artists' instead of singular 'artist'."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"artists": ["Artist A", "Artist B"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.artists == ["Artist A", "Artist B"]


def test_read_metadata_strips_whitespace_from_artists(tmp_path):
    """Some tags carry padding whitespace; the reader must strip it AND
    drop the empty entries that result."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"artist": ["  Real Artist  ", "", "  "]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.artists == ["Real Artist"]


def test_read_metadata_defaults_when_no_artist_tag(tmp_path):
    """A tag-less file falls back to the 'Unknown' sentinel."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.artists == ["Unknown"]
    assert meta.title == ""


def test_read_metadata_truncates_long_year(tmp_path):
    """Full ISO date '2013-05-17T07:00:00Z' → year is first 4 chars."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"date": ["2024-01-15T00:00:00Z"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.year == "2024"


# ─────────────────────────────────────────────────────────────────────────
# Track / disc number parsing
# ─────────────────────────────────────────────────────────────────────────

def test_track_number_parses_bare_int(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"tracknumber": ["7"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.track_n == 7


def test_track_number_parses_n_over_total(tmp_path):
    """The '8/13' format used by ID3 must extract just the n."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"tracknumber": ["8/13"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.track_n == 8


def test_track_number_zero_on_malformed(tmp_path):
    """Non-numeric track number falls back to 0."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"tracknumber": ["abc"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.track_n == 0


def test_disc_number_parses_n_over_total(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"discnumber": ["2/2"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.disc_n == 2


def test_disc_number_zero_on_malformed(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"discnumber": ["invalid"]})
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta.disc_n == 0


# ─────────────────────────────────────────────────────────────────────────
# Cover extraction (uses the non-easy File interface)
# ─────────────────────────────────────────────────────────────────────────

def test_read_metadata_extracts_cover_from_data_attribute(tmp_path):
    """MP3 APIC tags expose bytes via ``.data``."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    easy_audio = _mock_audio({})

    apic_tag = MagicMock()
    apic_tag.data = b"jpeg-bytes-here"
    full_audio = MagicMock()
    full_audio.tags = {"APIC:": apic_tag}

    def file_dispatch(_path, easy=False):
        return easy_audio if easy else full_audio
    with patch("mutagen.File", side_effect=file_dispatch):
        meta = read_metadata(path)
    assert meta.cover == b"jpeg-bytes-here"


def test_read_metadata_extracts_cover_from_value_attribute(tmp_path):
    """FLAC picture tags expose bytes via ``.value`` (not .data)."""
    path = tmp_path / "song.flac"
    path.write_bytes(b"x")
    easy_audio = _mock_audio({})

    picture_tag = MagicMock(spec=["value"])
    picture_tag.value = b"flac-picture-bytes"
    full_audio = MagicMock()
    full_audio.tags = {"metadata_block_picture": picture_tag}

    def file_dispatch(_path, easy=False):
        return easy_audio if easy else full_audio
    with patch("mutagen.File", side_effect=file_dispatch):
        meta = read_metadata(path)
    assert meta.cover == b"flac-picture-bytes"


def test_read_metadata_no_cover_when_tags_empty(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    easy_audio = _mock_audio({})
    full_audio = MagicMock()
    full_audio.tags = {}
    def file_dispatch(_path, easy=False):
        return easy_audio if easy else full_audio
    with patch("mutagen.File", side_effect=file_dispatch):
        meta = read_metadata(path)
    assert meta.cover == b""


def test_read_metadata_cover_extraction_error_is_silent(tmp_path):
    """If the full-tags open fails, don't lose the rest of the metadata —
    just leave cover empty and return the rest."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    easy_audio = _mock_audio({"title": ["Kept"]})
    def file_dispatch(_path, easy=False):
        if easy:
            return easy_audio
        raise RuntimeError("full-tags read exploded")
    with patch("mutagen.File", side_effect=file_dispatch):
        meta = read_metadata(path)
    assert meta.title == "Kept"
    assert meta.cover == b""


# ─────────────────────────────────────────────────────────────────────────
# Failure paths
# ─────────────────────────────────────────────────────────────────────────

def test_read_metadata_returns_none_when_file_unrecognized(tmp_path):
    """Mutagen returns None for unknown / corrupt formats."""
    path = tmp_path / "junk.xyz"
    path.write_bytes(b"garbage")
    with patch("mutagen.File", return_value=None):
        assert read_metadata(path) is None


def test_read_metadata_returns_none_on_mutagen_exception(tmp_path):
    """Mutagen raising must be caught — never propagate to caller."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    with patch("mutagen.File", side_effect=RuntimeError("mutagen crash")):
        assert read_metadata(path) is None


def test_read_metadata_missing_info_attribute_safe(tmp_path):
    """Some very old / stripped files have no ``audio.info`` at all.
    The reader must skip duration/bitrate extraction cleanly."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    audio = _mock_audio({"title": ["Something"]})
    del audio.info   # simulate the missing attribute
    with patch("mutagen.File", return_value=audio):
        meta = read_metadata(path)
    assert meta is not None
    assert meta.title    == "Something"
    assert meta.duration == 0.0     # default from dataclass
    assert meta.bitrate  == 0
