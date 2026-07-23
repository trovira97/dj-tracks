"""Tests for ``metadata.dj_metadata`` — the DJ enrichment orchestrator.

This module ties together Beatport, GetSongBPM, and librosa to enrich
every downloaded file with real BPM + Camelot key + genre + optional
ReplayGain and DJ-friendly filename.  A regression here silently
loses the DJ features that differentiate the app.

Focus:
- ``_normalise_key`` + ``key_to_camelot`` — unicode / enharmonic
  handling (different table from beatport.py — tested independently)
- ``cutoff_to_bitrate`` — spectral cutoff → estimated bitrate mapping
- ``upscale_cover_url`` — SoundCloud thumbnail upgrade
- ``replaygain_values`` — LUFS + peak → RG strings
- ``fp_similarity`` — Chromaprint bit-similarity
- ``_dj_rename`` — filename generation with regression guards for
  re-runs (avoid double-suffixing)
- ``chromaprint_available`` — subprocess wrapper
- ``lookup_getsongbpm`` — HTTP + best-match scoring
- ``_has_embedded_cover`` — mutagen presence check
- ``enrich_files`` — orchestrator control flow (mocked collaborators)
"""
from __future__ import annotations

import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from metadata.dj_metadata import (
    _dj_rename,
    _fuzzy,
    _has_embedded_cover,
    _normalise_key,
    chromaprint_available,
    cutoff_to_bitrate,
    enrich_files,
    fp_similarity,
    key_to_camelot,
    lookup_getsongbpm,
    replaygain_values,
    upscale_cover_url,
)


# ─────────────────────────────────────────────────────────────────────────
# _normalise_key + key_to_camelot
# ─────────────────────────────────────────────────────────────────────────

def test_normalise_key_infers_minor_from_trailing_m():
    assert _normalise_key("Am", None) == ("A", 0)


def test_normalise_key_infers_major_from_bare_note():
    assert _normalise_key("A", None) == ("A", 1)


def test_normalise_key_flat_to_sharp():
    """The internal table only has sharps; flats must be enharmonised."""
    root, mode = _normalise_key("Bb", None)
    assert root == "A#"
    assert mode == 1


def test_normalise_key_unicode_sharp_flat():
    """♯ and ♭ symbols must map to ASCII # and b before parsing."""
    r1, _ = _normalise_key("F♯", None)
    r2, _ = _normalise_key("A♭", None)
    assert r1 == "F#"
    assert r2 == "G#"    # Ab → G# (enharmonic)


def test_normalise_key_explicit_mode_overrides_string_inference():
    """If mode is passed explicitly it wins over the trailing-m heuristic."""
    _, m = _normalise_key("Am", "major")
    assert m == 1


def test_normalise_key_empty_returns_empty_root():
    assert _normalise_key("", None) == ("", 1)


def test_key_to_camelot_minor():
    """A minor → 8A on the Camelot wheel."""
    assert key_to_camelot("Am") == ("Am", "8A")


def test_key_to_camelot_major():
    assert key_to_camelot("C") == ("C", "8B")


def test_key_to_camelot_returns_empty_camelot_on_unknown_pitch():
    """Unknown pitch 'H' isn't in the Camelot table → camelot is empty
    but the musical string is still returned (root + mode suffix)."""
    musical, camelot = key_to_camelot("H maj")
    assert camelot == ""
    # musical mirrors what was passed (root, no suffix for major).
    assert musical == "H"


def test_key_to_camelot_flat_enharmonic():
    """Bb minor = A# minor → 3A."""
    musical, cam = key_to_camelot("Bbm")
    assert cam == "3A"


# ─────────────────────────────────────────────────────────────────────────
# _fuzzy
# ─────────────────────────────────────────────────────────────────────────

def test_fuzzy_identical_strings_score_100():
    assert _fuzzy("Get Lucky", "Get Lucky") == 100.0


def test_fuzzy_returns_zero_for_totally_different():
    """Even the fallback path (substring check) returns 0 on no overlap."""
    assert _fuzzy("hello", "world") < 100.0


def test_fuzzy_handles_none():
    assert _fuzzy(None, "x") >= 0.0
    assert _fuzzy("x", None) >= 0.0


# ─────────────────────────────────────────────────────────────────────────
# cutoff_to_bitrate
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("khz,expected", [
    (20.0, 320),
    (19.5, 320),
    (18.5, 256),
    (17.0, 192),
    (15.5, 128),
    (13.0, 96),
    (10.0, 64),
    (5.0,  64),
])
def test_cutoff_to_bitrate_mapping(khz, expected):
    assert cutoff_to_bitrate(khz) == expected


def test_cutoff_to_bitrate_none_returns_none():
    assert cutoff_to_bitrate(None) is None


# ─────────────────────────────────────────────────────────────────────────
# upscale_cover_url
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("small,expected_marker", [
    ("-large.",   "-t500x500."),
    ("-t67x67.",  "-t500x500."),
    ("-t120x120.","-t500x500."),
    ("-small.",   "-t500x500."),
    ("-tiny.",    "-t500x500."),
])
def test_upscale_cover_url_upgrades_known_suffixes(small, expected_marker):
    url = f"https://i1.sndcdn.com/artworks-abc{small}jpg"
    assert expected_marker in upscale_cover_url(url)


def test_upscale_cover_url_passes_through_unknown_format():
    """Unknown thumbnail format → return as-is (don't corrupt it)."""
    url = "https://cdn.example.com/cover.jpg"
    assert upscale_cover_url(url) == url


def test_upscale_cover_url_handles_empty():
    assert upscale_cover_url("") == ""


# ─────────────────────────────────────────────────────────────────────────
# replaygain_values
# ─────────────────────────────────────────────────────────────────────────

def test_replaygain_calculates_gain_from_lufs():
    """gain = reference - lufs; default reference = -18 LUFS."""
    gain, peak = replaygain_values(lufs=-14.0, peak_dbfs=-1.0)
    # -18 - (-14) = -4.00 dB
    assert gain == "-4.00 dB"


def test_replaygain_positive_gain_has_sign():
    """A quiet track (lufs -22) needs +4 dB to hit reference."""
    gain, _ = replaygain_values(lufs=-22.0, peak_dbfs=-6.0)
    assert gain == "+4.00 dB"


def test_replaygain_peak_converted_to_linear():
    """peak_dbfs=0 → linear peak = 1.0 (full-scale)."""
    _, peak = replaygain_values(lufs=-18.0, peak_dbfs=0.0)
    assert peak == "1.000000"


def test_replaygain_custom_reference():
    gain, _ = replaygain_values(lufs=-14.0, peak_dbfs=-1.0, reference=-23.0)
    # -23 - (-14) = -9.00 dB
    assert gain == "-9.00 dB"


# ─────────────────────────────────────────────────────────────────────────
# fp_similarity — Chromaprint bit similarity
# ─────────────────────────────────────────────────────────────────────────

def test_fp_similarity_identical_fingerprints_score_one():
    fp = [0x12345678, 0x9ABCDEF0, 0x11111111]
    assert fp_similarity(fp, fp) == 1.0


def test_fp_similarity_bitwise_opposite_score_zero():
    """All bits flipped → 0 out of 32 match per int."""
    a = [0x00000000]
    b = [0xFFFFFFFF]
    assert fp_similarity(a, b) == 0.0


def test_fp_similarity_partial_match_ratio():
    """One int with half bits matching = 0.5."""
    a = [0xFFFF0000]
    b = [0x00000000]
    assert fp_similarity(a, b) == 0.5


def test_fp_similarity_uses_shorter_length():
    """Different-length fingerprints compare only the first N ints where N
    is min(len(a), len(b))."""
    a = [0x12345678]
    b = [0x12345678, 0xFFFFFFFF]   # extra ints ignored
    assert fp_similarity(a, b) == 1.0


def test_fp_similarity_empty_or_none_score_zero():
    assert fp_similarity(None, [1, 2, 3]) == 0.0
    assert fp_similarity([1, 2, 3], None) == 0.0
    assert fp_similarity([], []) == 0.0


# ─────────────────────────────────────────────────────────────────────────
# _dj_rename
# ─────────────────────────────────────────────────────────────────────────

def test_dj_rename_appends_bpm_and_camelot(tmp_path):
    src = tmp_path / "Original.mp3"
    src.write_bytes(b"x")
    new = _dj_rename(str(src), {"bpm": 128, "camelot": "8A"})
    assert new is not None
    assert Path(new).name == "Original [128 - 8A].mp3"
    assert not src.exists()          # renamed away
    assert Path(new).exists()


def test_dj_rename_bpm_only():
    """No camelot / key → just the BPM in brackets."""
    # Don't actually rename — use a MagicMock filepath and just check the name.
    with patch("os.path.exists", return_value=False), \
         patch("os.rename"):
        new = _dj_rename("/x/Foo.mp3", {"bpm": 130})
    assert new is not None
    assert Path(new).name == "Foo [130].mp3"


def test_dj_rename_returns_none_when_no_info():
    """Nothing to append → return None instead of renaming."""
    assert _dj_rename("/x/Foo.mp3", {}) is None


def test_dj_rename_strips_existing_bpm_camelot_suffix(tmp_path):
    """Re-runs must not double-append.  'Foo [128 - 8A].mp3' →
    rename to 'Foo [130 - 5B].mp3', not 'Foo [128 - 8A] [130 - 5B].mp3'."""
    src = tmp_path / "Foo [128 - 8A].mp3"
    src.write_bytes(b"x")
    new = _dj_rename(str(src), {"bpm": 130, "camelot": "5B"})
    assert Path(new).name == "Foo [130 - 5B].mp3"


def test_dj_rename_avoids_clobbering_existing_target(tmp_path):
    """If the target filename already exists, bail out instead of
    overwriting silently."""
    src    = tmp_path / "A.mp3"
    target = tmp_path / "A [128 - 8A].mp3"
    src.write_bytes(b"x")
    target.write_bytes(b"y")   # pre-exists
    assert _dj_rename(str(src), {"bpm": 128, "camelot": "8A"}) is None
    # Both files must still exist untouched.
    assert src.exists()
    assert target.read_bytes() == b"y"


# ─────────────────────────────────────────────────────────────────────────
# chromaprint_available
# ─────────────────────────────────────────────────────────────────────────

def test_chromaprint_available_true_when_muxer_present():
    with patch("subprocess.run", return_value=MagicMock(
            stdout="muxers:\n E chromaprint chromaprint muxer\n E mp3 mp3")):
        assert chromaprint_available("ffmpeg") is True


def test_chromaprint_available_false_when_muxer_missing():
    with patch("subprocess.run", return_value=MagicMock(
            stdout="muxers:\n E mp3\n E flac")):
        assert chromaprint_available("ffmpeg") is False


def test_chromaprint_available_false_on_exception():
    """Subprocess error (ffmpeg not on PATH) → False, no crash."""
    with patch("subprocess.run", side_effect=FileNotFoundError):
        assert chromaprint_available("ffmpeg") is False


# ─────────────────────────────────────────────────────────────────────────
# lookup_getsongbpm
# ─────────────────────────────────────────────────────────────────────────

def _mock_gsbpm_response(payload, status=200):
    r = MagicMock()
    r.status_code = status
    r.json.return_value = payload
    session = MagicMock()
    session.get.return_value = r
    return session


def test_getsongbpm_returns_none_without_api_key():
    """No key = no request."""
    assert lookup_getsongbpm("A", "B", api_key="") is None


def test_getsongbpm_returns_none_without_query():
    assert lookup_getsongbpm("", "", api_key="KEY") is None


def test_getsongbpm_returns_none_on_http_error():
    session = _mock_gsbpm_response({}, status=500)
    assert lookup_getsongbpm("A", "B", api_key="K", session=session) is None


def test_getsongbpm_returns_none_on_empty_results():
    session = _mock_gsbpm_response({"search": []})
    assert lookup_getsongbpm("A", "B", api_key="K", session=session) is None


def test_getsongbpm_returns_none_when_no_match_above_threshold():
    """Best-match score < 55 → None (avoid returning garbage matches)."""
    session = _mock_gsbpm_response({"search": [
        {"song_title": "Completely Different",
         "artist": {"name": "Wrong Artist"}, "tempo": "120"},
    ]})
    assert lookup_getsongbpm("Daft Punk", "Get Lucky",
                              api_key="K", session=session) is None


def test_getsongbpm_returns_normalised_dict_on_hit():
    """A good match maps tempo/key_of/camelot/genres into the schema."""
    session = _mock_gsbpm_response({"search": [
        {"song_title": "Get Lucky",
         "artist": {"name": "Daft Punk", "genres": ["Nu Disco"]},
         "tempo": "116.0", "key_of": "F#m"},
    ]})
    result = lookup_getsongbpm("Daft Punk", "Get Lucky",
                                api_key="K", session=session)
    assert result is not None
    assert result["bpm"]     == 116
    assert result["key"]     == "F#m"
    assert result["camelot"] == "11A"   # F#m on Camelot wheel
    assert result["genre"]   == "Nu Disco"
    assert result["source"]  == "getsongbpm"


def test_getsongbpm_none_when_result_has_no_bpm_and_no_key():
    """A hit with neither tempo nor key_of is worthless — return None."""
    session = _mock_gsbpm_response({"search": [
        {"song_title": "Get Lucky",
         "artist": {"name": "Daft Punk"}, "tempo": None, "key_of": ""},
    ]})
    assert lookup_getsongbpm("Daft Punk", "Get Lucky",
                              api_key="K", session=session) is None


# ─────────────────────────────────────────────────────────────────────────
# _has_embedded_cover
# ─────────────────────────────────────────────────────────────────────────

def test_has_embedded_cover_mp3_true_when_apic_present():
    fake_tags = MagicMock()
    fake_tags.getall.return_value = ["APIC-frame"]
    with patch("mutagen.id3.ID3", return_value=fake_tags):
        assert _has_embedded_cover("/x/y.mp3", "mp3") is True


def test_has_embedded_cover_mp3_false_when_no_apic():
    fake_tags = MagicMock()
    fake_tags.getall.return_value = []
    with patch("mutagen.id3.ID3", return_value=fake_tags):
        assert _has_embedded_cover("/x/y.mp3", "mp3") is False


def test_has_embedded_cover_swallows_exception():
    """Corrupt file / mutagen exception → False, no crash."""
    with patch("mutagen.id3.ID3", side_effect=Exception("corrupt")):
        assert _has_embedded_cover("/x/y.mp3", "mp3") is False


def test_has_embedded_cover_returns_false_for_unsupported_format():
    """We only check MP3 and FLAC; other formats always return False."""
    assert _has_embedded_cover("/x/y.wav", "wav") is False


# ─────────────────────────────────────────────────────────────────────────
# enrich_files — orchestrator control flow
# ─────────────────────────────────────────────────────────────────────────

def test_enrich_files_empty_returns_zero_counts():
    result = enrich_files([], fmt="mp3")
    assert result["total"]  == 0
    assert result["tagged"] == 0
    assert result["renames"] == {}


def test_enrich_files_filters_missing_paths(tmp_path):
    """Entries whose path doesn't exist on disk are dropped upfront."""
    entries = [
        {"path": str(tmp_path / "exists.mp3"), "title": "A", "artist": "X"},
        {"path": "/does/not/exist.mp3",         "title": "B", "artist": "Y"},
    ]
    (tmp_path / "exists.mp3").write_bytes(b"x")
    with patch("metadata.dj_metadata.write_tags", return_value=True), \
         patch("metadata.beatport.lookup_beatport", return_value=None):
        result = enrich_files(entries, fmt="mp3")
    assert result["total"] == 1


def test_enrich_files_calls_beatport_first(tmp_path):
    """Beatport is the gold standard — must be tried before GetSongBPM."""
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    beatport_result = {"bpm": 128, "key": "8A", "camelot": "8A",
                        "source": "beatport"}

    with patch("metadata.beatport.lookup_beatport",
               return_value=beatport_result) as bp, \
         patch("metadata.dj_metadata.lookup_getsongbpm") as gsbpm, \
         patch("metadata.dj_metadata.write_tags", return_value=True):
        result = enrich_files([{"path": str(audio),
                                 "artist": "A", "title": "T"}],
                               fmt="mp3", api_key="apikey")
    bp.assert_called_once()
    # GetSongBPM must NOT be called when Beatport succeeded.
    gsbpm.assert_not_called()
    assert result["beatport"] == 1


def test_enrich_files_falls_back_to_getsongbpm_when_beatport_none(tmp_path):
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    gsbpm_result = {"bpm": 130, "key": "Am", "camelot": "8A",
                     "source": "getsongbpm"}

    with patch("metadata.beatport.lookup_beatport", return_value=None), \
         patch("metadata.dj_metadata.lookup_getsongbpm",
               return_value=gsbpm_result) as gsbpm, \
         patch("metadata.dj_metadata.write_tags", return_value=True):
        result = enrich_files([{"path": str(audio),
                                 "artist": "A", "title": "T"}],
                               fmt="mp3", api_key="apikey")
    gsbpm.assert_called_once()
    assert result["db"] == 1


def test_enrich_files_skips_getsongbpm_when_no_api_key(tmp_path):
    """Without an API key, GetSongBPM must NOT be called (returns 401)."""
    audio = tmp_path / "a.mp3"
    audio.write_bytes(b"x")
    with patch("metadata.beatport.lookup_beatport", return_value=None), \
         patch("metadata.dj_metadata.lookup_getsongbpm") as gsbpm, \
         patch("metadata.dj_metadata.analyze_local", return_value=None), \
         patch("metadata.dj_metadata.write_tags", return_value=True):
        enrich_files([{"path": str(audio), "artist": "A", "title": "T"}],
                     fmt="mp3", api_key="")   # ← no key
    gsbpm.assert_not_called()


def test_enrich_files_renames_when_dj_filename_enabled(tmp_path):
    """dj_filename=True + valid info → file gets a [BPM - Camelot] suffix."""
    audio = tmp_path / "song.mp3"
    audio.write_bytes(b"x")
    beatport_result = {"bpm": 128, "camelot": "8A", "source": "beatport"}
    with patch("metadata.beatport.lookup_beatport",
               return_value=beatport_result), \
         patch("metadata.dj_metadata.write_tags", return_value=True):
        result = enrich_files([{"path": str(audio),
                                 "artist": "A", "title": "T"}],
                               fmt="mp3", dj_filename=True)
    assert result["renamed"] == 1
    assert len(result["renames"]) == 1
    # Original path is the key, new path is the value.
    orig, new = next(iter(result["renames"].items()))
    assert orig == str(audio)
    assert "[128 - 8A]" in new


def test_enrich_files_stop_check_aborts_early(tmp_path):
    """A stop_check that returns False mid-loop must halt processing."""
    audio1 = tmp_path / "a.mp3"; audio1.write_bytes(b"x")
    audio2 = tmp_path / "b.mp3"; audio2.write_bytes(b"x")
    stop_called = [0]
    def stop_check():
        stop_called[0] += 1
        return False   # always request stop
    with patch("metadata.beatport.lookup_beatport", return_value=None), \
         patch("metadata.dj_metadata.write_tags"):
        result = enrich_files(
            [{"path": str(audio1), "artist": "A", "title": "T1"},
             {"path": str(audio2), "artist": "A", "title": "T2"}],
            fmt="mp3", stop_check=stop_check)
    # Should have exited without tagging either.
    assert result["tagged"] == 0
