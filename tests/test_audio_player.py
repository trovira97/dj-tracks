"""Tests for ``utils.audio_player`` — the pygame-backed preview player.

Focus on the parts that are testable without spinning up an actual
audio subsystem: the mutagen-based tag/duration/cover helpers, the
volume clamp, the queue navigation (next/prev/has_next/has_prev),
the observer pattern, and the state machine paths through play/stop/
seek/toggle_pause (with pygame.mixer.music mocked).

Explicitly NOT covered here:
- Actual audio playback (no real pygame mixer in tests)
- Real file I/O beyond touching a stub file so ``filepath.exists()``
  returns True

Note on singleton: AudioPlayer.get() returns a process-wide singleton.
Every test builds a fresh instance via ``AudioPlayer()`` to keep tests
isolated, and clears the class-level ``_instance`` in a fixture.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


def _install_fake_pygame() -> ModuleType:
    """Install a fake ``pygame`` module (with a mocked ``pygame.mixer.music``)
    in ``sys.modules`` so ``import pygame`` inside audio_player.py works
    even when the real pygame isn't installed in the dev environment.

    Every test that patches ``pygame.mixer.music`` needs this — pygame ships
    only with the frozen .exe, not the source-mode dev install.
    """
    pygame = ModuleType("pygame")
    mixer  = ModuleType("pygame.mixer")
    music  = MagicMock()   # replaced per-test via patch()

    mixer.init = MagicMock()
    mixer.music = music
    pygame.mixer = mixer

    sys.modules["pygame"] = pygame
    sys.modules["pygame.mixer"] = mixer
    return pygame


_install_fake_pygame()

# Import audio_player AFTER the fake pygame is in sys.modules — some
# helpers do their own inline `import pygame`.
from utils.audio_player import (  # noqa: E402
    AudioPlayer,
    _read_cover_bytes,
    _read_duration,
    _read_tags,
)


# ─────────────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_singleton():
    """AudioPlayer.get() caches an instance on the class — reset per test
    so we don't leak volume/queue state between cases."""
    AudioPlayer._instance = None
    yield
    AudioPlayer._instance = None


@pytest.fixture
def player():
    """A fresh AudioPlayer instance with the pygame mixer marked ready
    so state-mutating methods don't short-circuit."""
    p = AudioPlayer()
    p._ready = True
    return p


@pytest.fixture
def audio_file(tmp_path):
    p = tmp_path / "artist - song.mp3"
    p.write_bytes(b"stub-audio-bytes")
    return p


# ─────────────────────────────────────────────────────────────────────────
# _read_duration
# ─────────────────────────────────────────────────────────────────────────

def test_read_duration_returns_float(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    fake = MagicMock()
    fake.info.length = 210.5
    with patch("mutagen.File", return_value=fake):
        assert _read_duration(p) == 210.5


def test_read_duration_zero_when_mutagen_returns_none(tmp_path):
    """Unknown format → 0.0."""
    p = tmp_path / "x.xyz"
    p.write_bytes(b"x")
    with patch("mutagen.File", return_value=None):
        assert _read_duration(p) == 0.0


def test_read_duration_zero_on_exception(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    with patch("mutagen.File", side_effect=RuntimeError("corrupt")):
        assert _read_duration(p) == 0.0


def test_read_duration_zero_when_info_missing(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    fake = MagicMock(spec=[])   # no .info attribute
    with patch("mutagen.File", return_value=fake):
        assert _read_duration(p) == 0.0


# ─────────────────────────────────────────────────────────────────────────
# _read_tags
# ─────────────────────────────────────────────────────────────────────────

def test_read_tags_from_embedded(tmp_path):
    p = tmp_path / "whatever.mp3"
    p.write_bytes(b"x")
    fake = MagicMock()
    fake.tags = {"title": ["Real Title"], "artist": ["Real Artist"]}
    with patch("mutagen.File", return_value=fake):
        title, artist = _read_tags(p)
    assert title  == "Real Title"
    assert artist == "Real Artist"


def test_read_tags_falls_back_to_filename_pattern(tmp_path):
    """No tags in file → parse 'Artist - Title' from the filename."""
    p = tmp_path / "Daft Punk - Get Lucky.mp3"
    p.write_bytes(b"x")
    with patch("mutagen.File", return_value=None):
        title, artist = _read_tags(p)
    assert title  == "Get Lucky"
    assert artist == "Daft Punk"


def test_read_tags_filename_no_separator_uses_whole_name_as_title(tmp_path):
    """Filename without ' - ' → whole stem becomes the title, artist stays empty."""
    p = tmp_path / "single_word.mp3"
    p.write_bytes(b"x")
    with patch("mutagen.File", return_value=None):
        title, artist = _read_tags(p)
    assert title  == "single_word"
    assert artist == ""


def test_read_tags_fills_missing_side_from_filename(tmp_path):
    """Tags have artist but no title → fall back to filename for the missing side."""
    p = tmp_path / "Artist - Song.mp3"
    p.write_bytes(b"x")
    fake = MagicMock()
    fake.tags = {"artist": ["TagArtist"], "title": [""]}
    with patch("mutagen.File", return_value=fake):
        title, artist = _read_tags(p)
    assert artist == "TagArtist"
    assert title  == "Song"


def test_read_tags_exception_falls_back_to_filename(tmp_path):
    p = tmp_path / "A - B.mp3"
    p.write_bytes(b"x")
    with patch("mutagen.File", side_effect=RuntimeError("corrupt")):
        title, artist = _read_tags(p)
    assert (title, artist) == ("B", "A")


# ─────────────────────────────────────────────────────────────────────────
# _read_cover_bytes
# ─────────────────────────────────────────────────────────────────────────

def test_read_cover_bytes_from_mp3_apic(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    apic_tag = MagicMock()
    apic_tag.data = b"jpeg-bytes"
    fake = MagicMock()
    fake.tags = {"APIC:": apic_tag}
    with patch("mutagen.File", return_value=fake):
        assert _read_cover_bytes(p) == b"jpeg-bytes"


def test_read_cover_bytes_none_when_no_tags(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    fake = MagicMock()
    fake.tags   = {}
    fake.pictures = None
    with patch("mutagen.File", return_value=fake):
        assert _read_cover_bytes(p) is None


def test_read_cover_bytes_none_when_file_unknown(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    with patch("mutagen.File", return_value=None):
        assert _read_cover_bytes(p) is None


def test_read_cover_bytes_none_on_exception(tmp_path):
    p = tmp_path / "x.mp3"
    p.write_bytes(b"x")
    with patch("mutagen.File", side_effect=RuntimeError("corrupt")):
        assert _read_cover_bytes(p) is None


# ─────────────────────────────────────────────────────────────────────────
# Singleton
# ─────────────────────────────────────────────────────────────────────────

def test_get_returns_same_instance():
    p1 = AudioPlayer.get()
    p2 = AudioPlayer.get()
    assert p1 is p2


def test_fresh_instance_defaults():
    p = AudioPlayer()
    assert p._current    is None
    assert p._paused     is False
    assert p._volume     == 0.8
    assert p._queue      == []
    assert p._queue_idx  == -1


# ─────────────────────────────────────────────────────────────────────────
# set_volume — clamping + pygame call
# ─────────────────────────────────────────────────────────────────────────

def test_set_volume_clamps_to_0_1(player):
    with patch("pygame.mixer.music"):
        player.set_volume(1.5)
    assert player.volume == 1.0
    with patch("pygame.mixer.music"):
        player.set_volume(-0.3)
    assert player.volume == 0.0


def test_set_volume_within_range_passes_through(player):
    with patch("pygame.mixer.music"):
        player.set_volume(0.35)
    assert player.volume == 0.35


def test_set_volume_calls_pygame_when_ready(player):
    with patch("pygame.mixer.music") as music:
        player.set_volume(0.5)
    music.set_volume.assert_called_once_with(0.5)


def test_set_volume_skips_pygame_when_not_ready():
    """Pre-mixer-init: set_volume just stores locally, no pygame call."""
    p = AudioPlayer()  # _ready=False by default
    with patch("pygame.mixer.music") as music:
        p.set_volume(0.5)
    assert p.volume == 0.5
    music.set_volume.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# play / seek / stop / toggle_pause
# ─────────────────────────────────────────────────────────────────────────

def test_play_missing_file_returns_false(player, tmp_path):
    """File doesn't exist → no attempt, no crash."""
    assert player.play(tmp_path / "does-not-exist.mp3") is False


def test_play_loads_and_starts_pygame(player, audio_file):
    with patch("pygame.mixer.music") as music, \
         patch("utils.audio_player._read_duration", return_value=180.0), \
         patch("utils.audio_player._read_tags",     return_value=("T", "A")), \
         patch("utils.audio_player._read_cover_bytes", return_value=b"cover"):
        ok = player.play(audio_file)
    assert ok is True
    music.load.assert_called_once_with(str(audio_file))
    music.play.assert_called_once()
    assert player.current == audio_file
    assert player.title    == "T"
    assert player.duration == 180.0


def test_play_skips_tag_reload_on_seek(player, audio_file):
    """play(start=X) with X > 0 = seek, so we skip re-reading tags to
    avoid re-parsing the file on every slider drag."""
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration") as dur, \
         patch("utils.audio_player._read_tags") as tags:
        player.play(audio_file, start=30.0)
    dur.assert_not_called()
    tags.assert_not_called()
    assert player._start_pos == 30.0


def test_play_pygame_error_returns_false(player, audio_file):
    with patch("pygame.mixer.music") as music:
        music.load.side_effect = RuntimeError("bad file")
        assert player.play(audio_file) is False


def test_seek_none_when_nothing_playing(player):
    """seek with no current track → False, no side effects."""
    with patch("pygame.mixer.music"):
        assert player.seek(10.0) is False


def test_seek_replays_current_file_at_offset(player, audio_file):
    """seek delegates to play(current, start=seconds)."""
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)   # sets current
    with patch.object(player, "play", return_value=True) as p:
        player.seek(45.0)
    p.assert_called_once_with(audio_file, start=45.0)


def test_stop_clears_current(player, audio_file):
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)
    with patch("pygame.mixer.music") as music:
        player.stop()
    assert player.current is None
    assert player.paused is False
    music.stop.assert_called_once()


def test_stop_no_op_when_mixer_not_ready():
    p = AudioPlayer()   # _ready=False
    with patch("pygame.mixer.music") as music:
        p.stop()
    music.stop.assert_not_called()


def test_toggle_pause_pauses_and_resumes(player, audio_file):
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)

    with patch("pygame.mixer.music") as music:
        # First toggle: pause
        assert player.toggle_pause() is True
        music.pause.assert_called_once()
        assert player.paused is True

        # Second toggle: unpause
        assert player.toggle_pause() is False
        music.unpause.assert_called_once()
        assert player.paused is False


def test_toggle_pause_noop_when_nothing_playing(player):
    """No current track → False, no pygame call."""
    with patch("pygame.mixer.music") as music:
        assert player.toggle_pause() is False
    music.pause.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────
# is_playing
# ─────────────────────────────────────────────────────────────────────────

def test_is_playing_true_when_pygame_busy(player, audio_file):
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)
    with patch("pygame.mixer.music") as music:
        music.get_busy.return_value = True
        assert player.is_playing() is True


def test_is_playing_false_when_paused(player, audio_file):
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)
    player._paused = True
    with patch("pygame.mixer.music") as music:
        music.get_busy.return_value = True
        assert player.is_playing() is False


def test_is_playing_false_for_different_file(player, audio_file, tmp_path):
    """is_playing(path) returns True only when path matches the current track."""
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)
    other = tmp_path / "other.mp3"
    other.write_bytes(b"x")
    with patch("pygame.mixer.music") as music:
        music.get_busy.return_value = True
        assert player.is_playing(other) is False


def test_is_playing_false_when_nothing_loaded(player):
    assert player.is_playing() is False


# ─────────────────────────────────────────────────────────────────────────
# get_position
# ─────────────────────────────────────────────────────────────────────────

def test_get_position_zero_when_nothing_playing(player):
    """No current track → 0.0 with no pygame call."""
    assert player.get_position() == 0.0


def test_get_position_combines_start_offset_and_pygame_ms(player, audio_file):
    """pygame returns ms since last play(); we add the seek offset."""
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file, start=10.0)
    with patch("pygame.mixer.music") as music:
        music.get_pos.return_value = 5000   # 5 s since last play()
        assert player.get_position() == 15.0   # 10 + 5


def test_get_position_falls_back_to_start_pos_when_pygame_returns_negative(
        player, audio_file):
    """pygame returns -1 before any play() has happened yet."""
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags"), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file, start=25.0)
    with patch("pygame.mixer.music") as music:
        music.get_pos.return_value = -1
        assert player.get_position() == 25.0


# ─────────────────────────────────────────────────────────────────────────
# Queue navigation — next / prev / has_next / has_prev
# ─────────────────────────────────────────────────────────────────────────

def test_set_queue_resolves_current_index(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    b = tmp_path / "b.mp3"; b.write_bytes(b"x")
    c = tmp_path / "c.mp3"; c.write_bytes(b"x")
    player.set_queue([a, b, c], current=b)
    assert player._queue_idx == 1


def test_set_queue_missing_current_leaves_idx_negative(player, tmp_path):
    """A current that's not in the queue → idx=-1, next/prev are no-ops."""
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    b = tmp_path / "b.mp3"; b.write_bytes(b"x")
    player.set_queue([a, b], current=tmp_path / "other.mp3")
    assert player._queue_idx == -1


def test_next_plays_next_existing_track(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    b = tmp_path / "b.mp3"; b.write_bytes(b"x")
    player.set_queue([a, b], current=a)
    with patch.object(player, "play", return_value=True) as play:
        assert player.next() is True
    play.assert_called_once_with(b)
    assert player._queue_idx == 1


def test_next_skips_missing_files(player, tmp_path):
    """A deleted file mid-queue → skip to the next existing one."""
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    ghost = tmp_path / "ghost.mp3"    # never created
    c = tmp_path / "c.mp3"; c.write_bytes(b"x")
    player.set_queue([a, ghost, c], current=a)
    with patch.object(player, "play", return_value=True) as play:
        player.next()
    play.assert_called_once_with(c)
    assert player._queue_idx == 2


def test_next_returns_false_at_end_of_queue(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    player.set_queue([a], current=a)
    assert player.next() is False


def test_prev_plays_previous_track(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    b = tmp_path / "b.mp3"; b.write_bytes(b"x")
    player.set_queue([a, b], current=b)
    with patch.object(player, "play", return_value=True) as play:
        assert player.prev() is True
    play.assert_called_once_with(a)


def test_prev_returns_false_at_start_of_queue(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    player.set_queue([a], current=a)
    assert player.prev() is False


def test_has_next_reflects_availability(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    b = tmp_path / "b.mp3"; b.write_bytes(b"x")
    player.set_queue([a, b], current=a)
    assert player.has_next is True
    player.set_queue([a, b], current=b)
    assert player.has_next is False


def test_has_prev_reflects_availability(player, tmp_path):
    a = tmp_path / "a.mp3"; a.write_bytes(b"x")
    b = tmp_path / "b.mp3"; b.write_bytes(b"x")
    player.set_queue([a, b], current=b)
    assert player.has_prev is True
    player.set_queue([a, b], current=a)
    assert player.has_prev is False


def test_next_and_prev_are_noop_when_no_queue(player):
    assert player.next() is False
    assert player.prev() is False


# ─────────────────────────────────────────────────────────────────────────
# Observer pattern
# ─────────────────────────────────────────────────────────────────────────

def test_subscribe_fires_on_state_change(player, audio_file):
    calls = []
    player.subscribe(lambda: calls.append("fired"))
    with patch("pygame.mixer.music"), \
         patch("utils.audio_player._read_duration"), \
         patch("utils.audio_player._read_tags", return_value=("T", "A")), \
         patch("utils.audio_player._read_cover_bytes"):
        player.play(audio_file)
    assert calls == ["fired"]


def test_subscribe_multiple_callbacks_all_fire(player):
    calls = []
    for i in range(3):
        player.subscribe(lambda idx=i: calls.append(idx))
    player._fire_state_change()
    assert sorted(calls) == [0, 1, 2]


def test_subscribe_callback_exception_does_not_break_others(player):
    """One bad observer must not prevent others from firing."""
    calls = []
    player.subscribe(lambda: (_ for _ in ()).throw(RuntimeError("boom")))
    player.subscribe(lambda: calls.append("survived"))
    player._fire_state_change()   # must not raise
    assert calls == ["survived"]
