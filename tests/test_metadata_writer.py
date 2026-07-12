"""Tests for ``metadata.metadata_writer``.

The writer is the last step of a successful download — it stamps the
final .mp3/.flac/.m4a/.ogg file with title, artist, album, cover,
year, ISRC, and track numbers so the user's DJ software and library
manager can see clean metadata.  A broken writer means every future
download ships with bad tags until someone notices.

Focus:
- ``download_cover`` — HTTP fetch with content-type and size guards
- ``write_metadata`` — format dispatch by file extension
- ``verify_and_fix`` — read-back comparison + selective rewrite
- Format-specific writers: error path (mutagen raises → False)
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from metadata.metadata_reader import AudioMetadata
from metadata.metadata_writer import (
    _MAX_COVER_BYTES,
    _write_flac,
    _write_m4a,
    _write_mp3,
    _write_ogg,
    download_cover,
    verify_and_fix,
    write_metadata,
)
from providers import TrackInfo


# ─────────────────────────────────────────────────────────────────────────
# download_cover
# ─────────────────────────────────────────────────────────────────────────

def _mock_get(content=b"jpeg-bytes", content_type="image/jpeg", ok=True):
    """Build a mocked requests.get return value."""
    r = MagicMock()
    r.content = content
    r.headers = {"Content-Type": content_type}
    r.raise_for_status = MagicMock() if ok else \
                         MagicMock(side_effect=Exception("HTTP 5xx"))
    return r


def test_download_cover_returns_bytes_on_success():
    with patch("metadata.metadata_writer.requests.get",
               return_value=_mock_get(content=b"actual-jpeg")):
        assert download_cover("https://cover/x.jpg") == b"actual-jpeg"


def test_download_cover_empty_url_returns_none():
    """Empty / missing URL → None without an HTTP call at all."""
    with patch("metadata.metadata_writer.requests.get") as gt:
        assert download_cover("") is None
        assert download_cover(None) is None
    gt.assert_not_called()


def test_download_cover_rejects_non_image_content_type():
    """A URL that serves HTML (redirect page, 404 shell) → None."""
    with patch("metadata.metadata_writer.requests.get",
               return_value=_mock_get(content_type="text/html")):
        assert download_cover("https://cover/x") is None


def test_download_cover_allows_missing_content_type():
    """Some CDNs omit Content-Type entirely — accept the payload rather
    than reject silently."""
    with patch("metadata.metadata_writer.requests.get",
               return_value=_mock_get(content_type="")):
        assert download_cover("https://cover/x.jpg") == b"jpeg-bytes"


def test_download_cover_rejects_oversized_image():
    """Guard against a compromised URL that dumps a multi-GB blob into
    the tag."""
    huge = b"x" * (_MAX_COVER_BYTES + 1)
    with patch("metadata.metadata_writer.requests.get",
               return_value=_mock_get(content=huge)):
        assert download_cover("https://cover/x.jpg") is None


def test_download_cover_swallows_network_error():
    """Timeout / connection reset → None, never raise into the caller."""
    with patch("metadata.metadata_writer.requests.get",
               side_effect=Exception("timeout")):
        assert download_cover("https://cover/x.jpg") is None


def test_download_cover_swallows_http_error():
    with patch("metadata.metadata_writer.requests.get",
               return_value=_mock_get(ok=False)):
        assert download_cover("https://cover/x.jpg") is None


# ─────────────────────────────────────────────────────────────────────────
# write_metadata — format dispatch
# ─────────────────────────────────────────────────────────────────────────

def _track(**kw):
    kw.setdefault("title", "T")
    kw.setdefault("artists", ["A"])
    return TrackInfo(**kw)


@pytest.mark.parametrize("ext,handler_name", [
    (".mp3",  "_write_mp3"),
    (".flac", "_write_flac"),
    (".m4a",  "_write_m4a"),
    (".mp4",  "_write_m4a"),   # same handler as m4a
    (".aac",  "_write_m4a"),   # same handler as m4a
    (".ogg",  "_write_ogg"),
])
def test_write_metadata_dispatches_by_extension(tmp_path, ext, handler_name):
    """Each extension routes to its dedicated handler."""
    path = tmp_path / f"song{ext}"
    path.write_bytes(b"x")
    with patch(f"metadata.metadata_writer.{handler_name}",
               return_value=True) as h:
        assert write_metadata(path, _track()) is True
    h.assert_called_once()


def test_write_metadata_unknown_extension_returns_false(tmp_path):
    path = tmp_path / "song.opus"
    path.write_bytes(b"x")
    assert write_metadata(path, _track()) is False


def test_write_metadata_case_insensitive_extension(tmp_path):
    """Uppercase '.MP3' still dispatches to _write_mp3."""
    path = tmp_path / "song.MP3"
    path.write_bytes(b"x")
    with patch("metadata.metadata_writer._write_mp3",
               return_value=True) as h:
        assert write_metadata(path, _track()) is True
    h.assert_called_once()


def test_write_metadata_returns_false_when_handler_raises(tmp_path):
    """Handler exceptions must be caught — the caller (Controller) uses
    write_metadata's return value to decide whether to log an error."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    with patch("metadata.metadata_writer._write_mp3",
               side_effect=RuntimeError("mutagen exploded")):
        assert write_metadata(path, _track()) is False


# ─────────────────────────────────────────────────────────────────────────
# Format-specific writers — error paths
# ─────────────────────────────────────────────────────────────────────────

def test_write_mp3_returns_false_on_mutagen_error(tmp_path):
    """The MP3 handler must return False when the ID3 tags can't be
    saved — corrupt file, permission error, disk full, etc."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"not a real mp3")
    # ID3 will raise inside; we just need to confirm the handler returns False.
    with patch("metadata.metadata_writer.ID3",
               side_effect=RuntimeError("corrupt file")):
        assert _write_mp3(path, _track(), cover=None) is False


def test_write_flac_returns_false_on_mutagen_error(tmp_path):
    path = tmp_path / "song.flac"
    path.write_bytes(b"x")
    with patch("metadata.metadata_writer.FLAC",
               side_effect=RuntimeError("not a flac")):
        assert _write_flac(path, _track(), cover=None) is False


def test_write_m4a_returns_false_on_mutagen_error(tmp_path):
    path = tmp_path / "song.m4a"
    path.write_bytes(b"x")
    with patch("metadata.metadata_writer.MP4",
               side_effect=RuntimeError("bad m4a")):
        assert _write_m4a(path, _track(), cover=None) is False


def test_write_ogg_returns_false_on_mutagen_error(tmp_path):
    path = tmp_path / "song.ogg"
    path.write_bytes(b"x")
    with patch("metadata.metadata_writer.OggVorbis",
               side_effect=RuntimeError("bad ogg")):
        assert _write_ogg(path, _track(), cover=None) is False


# ─────────────────────────────────────────────────────────────────────────
# MP3 tag-content tests via a MagicMock ID3 instance
# ─────────────────────────────────────────────────────────────────────────

def _mock_id3_ctor(existing_tags=None):
    """Return a patch context that swaps ``ID3`` with a MagicMock
    yielding a fresh tag object each time.  ``existing_tags`` is
    ignored — the mock tracks .add() and .save() calls instead."""
    tag_obj = MagicMock()
    return patch("metadata.metadata_writer.ID3", return_value=tag_obj), tag_obj


def test_write_mp3_writes_title_artist_album_from_track(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    tag_obj = MagicMock()
    with patch("metadata.metadata_writer.ID3", return_value=tag_obj):
        assert _write_mp3(path, _track(title="Get Lucky",
                                        artists=["Daft Punk"],
                                        album="RAM"), cover=None) is True
    # save() called (that's the real assertion: we ran to completion).
    tag_obj.save.assert_called_once()
    save_args = tag_obj.save.call_args
    # Must save as ID3v2.3 (widest DJ software compat).
    assert save_args[1]["v2_version"] == 3


def test_write_mp3_recovers_from_id3_no_header_error(tmp_path):
    """A fresh MP3 without any ID3 tags raises ID3NoHeaderError; the
    handler must catch it and start with an empty ID3() instance."""
    from mutagen.id3 import ID3NoHeaderError
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    tag_obj = MagicMock()
    # First call raises (opening file), fallback constructor call returns empty.
    with patch("metadata.metadata_writer.ID3",
               side_effect=[ID3NoHeaderError(), tag_obj]):
        assert _write_mp3(path, _track(), cover=None) is True
    tag_obj.save.assert_called_once()


def test_write_mp3_embeds_cover_when_provided(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    tag_obj = MagicMock()
    with patch("metadata.metadata_writer.ID3", return_value=tag_obj):
        _write_mp3(path, _track(), cover=b"jpeg-bytes")
    # Look for an APIC add call in the mock's history.
    apic_added = any(
        args[0].__class__.__name__ == "APIC"
        for name, args, _ in tag_obj.add.mock_calls
        if args
    )
    assert apic_added


def test_write_mp3_no_cover_no_apic(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    tag_obj = MagicMock()
    with patch("metadata.metadata_writer.ID3", return_value=tag_obj):
        _write_mp3(path, _track(), cover=None)
    apic_calls = [
        c for name, args, _ in tag_obj.add.mock_calls
        for c in args if c.__class__.__name__ == "APIC"
    ]
    assert not apic_calls


# ─────────────────────────────────────────────────────────────────────────
# verify_and_fix — compare then rewrite
# ─────────────────────────────────────────────────────────────────────────

def _current(**kw):
    kw.setdefault("title", "Old Title")
    kw.setdefault("album", "Old Album")
    kw.setdefault("year", "2020")
    kw.setdefault("track_n", 1)
    kw.setdefault("artists", ["Old Artist"])
    # verify_and_fix() compares album_artist against
    # (track.album_artist or track.artist_str), so if a test sets
    # 'artists' but not 'album_artist', the compare would spuriously
    # diff as ("", <artist>).  Default to matching the artist_str.
    kw.setdefault("album_artist", ", ".join(kw["artists"]))
    return AudioMetadata(**kw)


def test_verify_no_corrections_when_metadata_matches(tmp_path):
    """Nothing differs → no corrections dict, no write."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="Same", artists=["A"], album="B", year="2020")
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata") as wm:
        result = verify_and_fix(path, TrackInfo(title="Same", artists=["A"],
                                                  album="B", year="2020"))
    assert result == {}
    wm.assert_not_called()


def test_verify_flags_title_diff_and_rewrites(tmp_path):
    """Different title → corrections logged AND write_metadata called."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="Wrong Title", artists=["A"],
                       album="B", year="2020")
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata") as wm, \
         patch("metadata.metadata_writer.download_cover", return_value=None):
        result = verify_and_fix(path,
                                TrackInfo(title="Right Title", artists=["A"],
                                          album="B", year="2020"))
    assert "title" in result
    assert result["title"] == ("Wrong Title", "Right Title")
    wm.assert_called_once()


def test_verify_ignores_case_and_whitespace_differences(tmp_path):
    """Diff is case-insensitive and trims — 'foo' == 'FOO ' == '  foo'."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="FOO ", artists=["  A  "],
                       album="  Album  ", year="2020")
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata") as wm:
        result = verify_and_fix(path,
                                TrackInfo(title="foo", artists=["a"],
                                          album="album", year="2020"))
    assert result == {}
    wm.assert_not_called()


def test_verify_does_not_flag_when_expected_is_empty(tmp_path):
    """If we don't know the expected value (e.g. genre unset in TrackInfo),
    don't overwrite whatever's already on disk with empty."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="Something", artists=["A"],
                       album="B", year="2020")
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata") as wm:
        # Empty title expected → don't flag as diff
        result = verify_and_fix(path,
                                TrackInfo(title="", artists=["A"],
                                          album="B", year="2020"))
    assert "title" not in result
    wm.assert_not_called()


def test_verify_flags_multiple_fields(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="Wrong", artists=["OldArt"], album="Old",
                       year="2020")
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata"), \
         patch("metadata.metadata_writer.download_cover"):
        result = verify_and_fix(path,
                                TrackInfo(title="Right", artists=["NewArt"],
                                          album="New", year="2023"))
    assert set(result.keys()) >= {"title", "artist", "album", "year"}


def test_verify_flags_track_number_diff(tmp_path):
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="T", artists=["A"], album="B",
                       year="2020", track_n=1)
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata"), \
         patch("metadata.metadata_writer.download_cover"):
        result = verify_and_fix(path,
                                TrackInfo(title="T", artists=["A"],
                                          album="B", year="2020",
                                          track_number=5))
    assert result["track_number"] == ("1", "5")


def test_verify_downloads_cover_when_url_present_and_corrections_needed(tmp_path):
    """When corrections trigger a rewrite AND we have a cover URL,
    also download the cover so the rewrite carries fresh artwork."""
    path = tmp_path / "song.mp3"
    path.write_bytes(b"x")
    current = _current(title="Wrong")
    with patch("metadata.metadata_writer.read_metadata",
               return_value=current), \
         patch("metadata.metadata_writer.write_metadata"), \
         patch("metadata.metadata_writer.download_cover",
               return_value=b"cover") as dl:
        verify_and_fix(path,
                        TrackInfo(title="Right", artists=["A"],
                                  cover_url="https://cover.jpg"))
    dl.assert_called_once_with("https://cover.jpg")


def test_verify_returns_empty_when_read_metadata_fails(tmp_path):
    """Read fails (unsupported format) → skip verification cleanly."""
    path = tmp_path / "song.opus"
    path.write_bytes(b"x")
    with patch("metadata.metadata_writer.read_metadata", return_value=None), \
         patch("metadata.metadata_writer.write_metadata") as wm:
        result = verify_and_fix(path, TrackInfo(title="X", artists=["A"]))
    assert result == {}
    wm.assert_not_called()
