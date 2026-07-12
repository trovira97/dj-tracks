"""Tests for ``providers.youtube_provider``.

YouTube is a mixed source: yt-dlp does the download, this provider
just wraps yt-dlp's extract_info to produce TrackInfo objects.  The
value-adds worth testing are the fallible pure-logic helpers that
massage messy YT titles into artist/title pairs.

Focus:
- ``_clean_title`` — strip noise tags like ``(Official Video)``, ``[HD]``
- ``_split_artist_title`` — Artist–Title fallback with unicode dashes,
  ``- Topic`` channel suffix, and cases with no separator
- ``_best_thumbnail`` — pick the largest URL from yt-dlp's list
- ``_entry_to_info`` — full mapping including structured track/artist
  tags (YT Music) vs title-splitting fallback
- Not-available path (yt_dlp import fails)
- URL routing:
  * single video URL
  * playlist URL (detected by ``?list=`` regex)
  * plain ID (11-char) treated as a video ID
  * channel / topic URL → empty (out of scope)
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from providers.youtube_provider import (
    YouTubeProvider,
    _best_thumbnail,
    _clean_title,
    _entry_to_info,
    _split_artist_title,
)


# ─────────────────────────────────────────────────────────────────────────
# _clean_title
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("raw,expected", [
    ("Artist - Track (Official Video)",       "Artist - Track"),
    ("Artist - Track (Official Music Video)", "Artist - Track"),
    ("Artist - Track [Official Video]",       "Artist - Track"),
    ("Artist - Track (Audio)",                "Artist - Track"),
    ("Artist - Track (Lyrics)",               "Artist - Track"),
    ("Artist - Track [HD]",                   "Artist - Track"),
    ("Artist - Track (MV)",                   "Artist - Track"),
    # Multiple noise tags → strip them all iteratively.
    ("Artist - Track (Official Video) [HD]",  "Artist - Track"),
])
def test_clean_title_strips_noise(raw, expected):
    assert _clean_title(raw) == expected


def test_clean_title_case_insensitive():
    assert _clean_title("Foo - Bar (OFFICIAL VIDEO)") == "Foo - Bar"


def test_clean_title_leaves_content_without_noise():
    """A clean title stays intact."""
    assert _clean_title("Artist - Real Title") == "Artist - Real Title"


def test_clean_title_handles_empty_input():
    assert _clean_title("") == ""
    assert _clean_title(None) == ""


# ─────────────────────────────────────────────────────────────────────────
# _split_artist_title
# ─────────────────────────────────────────────────────────────────────────

def test_split_ascii_dash():
    a, t = _split_artist_title("Daft Punk - Get Lucky", "irrelevant")
    assert (a, t) == ("Daft Punk", "Get Lucky")


def test_split_em_dash():
    a, t = _split_artist_title("Daft Punk — Get Lucky", "irrelevant")
    assert (a, t) == ("Daft Punk", "Get Lucky")


def test_split_en_dash():
    a, t = _split_artist_title("Daft Punk – Get Lucky", "irrelevant")
    assert (a, t) == ("Daft Punk", "Get Lucky")


def test_split_falls_back_to_uploader_when_no_dash():
    """No separator in title → uploader becomes the artist."""
    a, t = _split_artist_title("Some Track Name", "Some Uploader")
    assert (a, t) == ("Some Uploader", "Some Track Name")


def test_split_strips_topic_suffix_from_uploader():
    """YouTube Music auto-generates 'Artist - Topic' channels for labels.
    We strip the ' - Topic' so the artist name is clean."""
    a, t = _split_artist_title("Song", "Daft Punk - Topic")
    assert a == "Daft Punk"


def test_split_uses_only_first_dash_for_multi_dash_titles():
    """Titles like 'Artist - Song - Remix' should split on the FIRST dash
    only; the rest stays as part of the title."""
    a, t = _split_artist_title("Artist - Song - Remix", "irrelevant")
    assert a == "Artist"
    assert "Song" in t


def test_split_fallback_when_both_empty():
    a, t = _split_artist_title("", "")
    assert (a, t) == ("Unknown", "Unknown")


def test_split_returns_uploader_when_split_yields_empty_side():
    """A title like ' - Foo' or 'Foo - ' has an empty artist or title —
    fall back to uploader rather than emit empty fields."""
    a, t = _split_artist_title(" - Foo", "Some Uploader")
    # First side empty → use uploader as artist.
    assert a == "Some Uploader"


# ─────────────────────────────────────────────────────────────────────────
# _best_thumbnail
# ─────────────────────────────────────────────────────────────────────────

def test_best_thumbnail_picks_largest_by_width():
    thumbs = [
        {"url": "sm.jpg", "width": 120},
        {"url": "md.jpg", "width": 480},
        {"url": "lg.jpg", "width": 1280},
    ]
    assert _best_thumbnail(thumbs) == "lg.jpg"


def test_best_thumbnail_picks_last_when_no_widths():
    """yt-dlp orders thumbnails by ascending quality; without widths,
    the last entry is the largest."""
    thumbs = [{"url": "a.jpg"}, {"url": "b.jpg"}, {"url": "c.jpg"}]
    assert _best_thumbnail(thumbs) == "c.jpg"


def test_best_thumbnail_prefers_widthed_entries():
    """Entries WITH widths take precedence over entries without."""
    thumbs = [
        {"url": "no-width-1.jpg"},
        {"url": "small.jpg",  "width": 100},
        {"url": "large.jpg",  "width": 500},
        {"url": "no-width-2.jpg"},   # trailing entries without widths
    ]
    assert _best_thumbnail(thumbs) == "large.jpg"


def test_best_thumbnail_empty_or_none():
    assert _best_thumbnail([]) == ""
    assert _best_thumbnail(None) == ""


# ─────────────────────────────────────────────────────────────────────────
# _entry_to_info
# ─────────────────────────────────────────────────────────────────────────

def test_entry_to_info_from_ytmusic_tags():
    """When yt-dlp extracted structured 'track' and 'artist' tags (YouTube
    Music), use them verbatim instead of splitting the video title."""
    entry = {
        "id":       "abc123",
        "title":    "Ignored Video Title",
        "track":    "Get Lucky",
        "artist":   "Daft Punk",
        "webpage_url": "https://youtube.com/watch?v=abc123",
        "duration": 369,
        "thumbnails": [{"url": "t.jpg", "width": 1280}],
    }
    ti = _entry_to_info(entry)
    assert ti is not None
    assert ti.title       == "Get Lucky"
    assert ti.artists     == ["Daft Punk"]
    assert ti.platform    == "youtube"
    assert ti.track_id    == "abc123"
    assert ti.duration_ms == 369_000
    assert ti.cover_url   == "t.jpg"


def test_entry_to_info_from_split_when_no_music_tags():
    entry = {
        "id":       "xyz",
        "title":    "Beyoncé - Halo (Official Video)",
        "uploader": "BeyonceVEVO",
        "webpage_url": "https://youtube.com/watch?v=xyz",
        "duration": 200,
    }
    ti = _entry_to_info(entry)
    assert ti.artists == ["Beyoncé"]
    assert ti.title   == "Halo"


def test_entry_to_info_builds_url_from_id_when_no_webpage_url():
    """Some yt-dlp responses omit webpage_url (flat playlist entries);
    we should build the canonical watch URL from the id."""
    entry = {"id": "xyz789", "title": "Foo - Bar", "uploader": "up"}
    ti = _entry_to_info(entry)
    assert ti.source_url == "https://www.youtube.com/watch?v=xyz789"


def test_entry_to_info_returns_none_when_no_id_and_no_url():
    """No id + no webpage_url → we can't build a source URL, drop the entry."""
    entry = {"title": "Foo - Bar"}
    assert _entry_to_info(entry) is None


def test_entry_to_info_returns_none_on_non_dict_input():
    assert _entry_to_info(None) is None
    assert _entry_to_info("garbage") is None


def test_entry_to_info_handles_missing_duration():
    entry = {"id": "x", "title": "A - B", "uploader": "up"}
    ti = _entry_to_info(entry)
    assert ti.duration_ms == 0


def test_entry_to_info_strips_topic_from_uploader():
    """When falling back to uploader, ' - Topic' suffix is stripped."""
    entry = {"id": "x", "title": "Nice Song",
             "uploader": "Some Artist - Topic"}
    ti = _entry_to_info(entry)
    assert ti.artists == ["Some Artist"]


# ─────────────────────────────────────────────────────────────────────────
# Provider — not-available paths
# ─────────────────────────────────────────────────────────────────────────

def _bare_provider(available: bool):
    """Build a YouTubeProvider without touching yt_dlp import."""
    p = YouTubeProvider.__new__(YouTubeProvider)
    p._available = available
    return p


def test_provider_name_property():
    assert _bare_provider(True).name == "YouTube"


def test_available_reflects_state():
    assert _bare_provider(True).available is True
    assert _bare_provider(False).available is False


def test_search_empty_when_unavailable():
    assert _bare_provider(False).search("query") == []


def test_search_empty_when_query_empty():
    assert _bare_provider(True).search("   ") == []


def test_get_track_none_when_unavailable():
    assert _bare_provider(False).get_track("abc123") is None


def test_get_tracks_from_url_empty_when_unavailable():
    assert _bare_provider(False).get_tracks_from_url(
        "https://www.youtube.com/watch?v=x") == []


# ─────────────────────────────────────────────────────────────────────────
# Provider — search / get_track / get_tracks_from_url with mocked _extract
# ─────────────────────────────────────────────────────────────────────────

def test_search_returns_mapped_entries():
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract", return_value={
        "entries": [
            {"id": "a", "title": "Artist - Song A", "uploader": "u"},
            {"id": "b", "title": "Artist - Song B", "uploader": "u"},
        ]
    }):
        out = p.search("query", limit=5)
    assert len(out) == 2
    assert out[0].title == "Song A"


def test_search_respects_limit():
    """Even if yt-dlp returns more than N, we cap at limit."""
    p = _bare_provider(True)
    entries = [{"id": str(i), "title": f"A - S{i}", "uploader": "u"}
               for i in range(20)]
    with patch.object(YouTubeProvider, "_extract",
                      return_value={"entries": entries}):
        out = p.search("query", limit=3)
    assert len(out) == 3


def test_search_returns_empty_when_extract_returns_none():
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract", return_value=None):
        assert p.search("query") == []


def test_get_track_accepts_bare_id():
    """A plain 11-char ID should be converted to a watch URL before extract."""
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract",
                      return_value={"id": "abc12345678",
                                    "title": "A - B",
                                    "uploader": "u"}) as ext:
        p.get_track("abc12345678")
    call_arg = ext.call_args[0][0]
    assert call_arg.startswith("https://www.youtube.com/watch?v=")


def test_get_track_accepts_full_url():
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract",
                      return_value={"id": "abc",
                                    "title": "A - B",
                                    "uploader": "u"}) as ext:
        p.get_track("https://www.youtube.com/watch?v=abc")
    call_arg = ext.call_args[0][0]
    assert call_arg == "https://www.youtube.com/watch?v=abc"


def test_get_track_none_when_extract_returns_none():
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract", return_value=None):
        assert p.get_track("abc") is None


def test_get_tracks_from_url_single_video():
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract",
                      return_value={"id": "abc",
                                    "title": "A - B",
                                    "uploader": "u"}) as ext:
        out = p.get_tracks_from_url("https://youtu.be/abc")
    # Single-video call must NOT be flat.
    assert ext.call_args[1]["flat"] is False
    assert len(out) == 1


def test_get_tracks_from_url_playlist_detected_by_list_param():
    """URLs with ?list= are playlists; extract flat + iterate entries."""
    p = _bare_provider(True)
    playlist_url = "https://www.youtube.com/watch?v=abc&list=PLxxx"
    with patch.object(YouTubeProvider, "_extract", return_value={
        "entries": [
            {"id": "e1", "title": "A - S1", "uploader": "u"},
            {"id": "e2", "title": "A - S2", "uploader": "u"},
        ]
    }) as ext:
        out = p.get_tracks_from_url(playlist_url)
    # Playlist call must be flat.
    assert ext.call_args[1]["flat"] is True
    assert len(out) == 2


def test_get_tracks_from_url_returns_empty_on_extract_failure():
    p = _bare_provider(True)
    with patch.object(YouTubeProvider, "_extract", return_value=None):
        assert p.get_tracks_from_url("https://youtu.be/x") == []


def test_get_tracks_from_url_falls_back_to_single_when_no_entries_key():
    """A URL that had ?list= but returned no 'entries' key → treat as
    single video (rare edge case with private playlists)."""
    p = _bare_provider(True)
    playlist_url = "https://www.youtube.com/watch?v=abc&list=PLxxx"
    with patch.object(YouTubeProvider, "_extract",
                      return_value={"id": "abc", "title": "A - B",
                                    "uploader": "u"}):
        out = p.get_tracks_from_url(playlist_url)
    assert len(out) == 1
