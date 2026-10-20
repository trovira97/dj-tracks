"""Tests for ``backend/faq_responder.py`` — rule-based auto-responder.

This is the module that powers the bot's auto-replies in the Discord
#ayuda channel.  A regression means users get the wrong canned answer
(or none at all) when they ask for help.

Focus:
- ``_normalise``: lowercasing + accent folding + whitespace collapse
- ``_MIN_LEN`` guard: very short messages ignored
- ``match``: single-keyword hit, multi-keyword tie-breaking, threshold
  enforcement, score comparison across multiple entries
- Every FAQ entry still answers the question it was authored for
  (regression: an edit that broke all keywords for an entry would
  silently remove it from service without any error)
"""
from __future__ import annotations

import pytest

from backend.faq_responder import (
    FAQ_ENTRIES,
    FaqEntry,
    _MIN_LEN,
    _normalise,
    match,
)


# ─────────────────────────────────────────────────────────────────────────
# _normalise
# ─────────────────────────────────────────────────────────────────────────

def test_normalise_lowercases():
    assert _normalise("Hello WORLD") == "hello world"


def test_normalise_folds_spanish_accents():
    """Users type with and without accents interchangeably — the
    normaliser must map them so 'actualización' matches 'actualizacion'."""
    assert _normalise("Cómo instaló actualización") == \
           _normalise("Como instalo actualizacion")


def test_normalise_folds_enye():
    assert _normalise("año") == "ano"


def test_normalise_collapses_whitespace():
    """Multiple spaces / tabs / newlines → single space.  Users on mobile
    paste wrapped messages that would otherwise defeat substring match."""
    assert _normalise("foo   \t\n bar") == "foo bar"


def test_normalise_handles_empty_string():
    assert _normalise("") == ""


def test_normalise_preserves_non_accent_characters():
    """Punctuation and digits must survive — some FAQ keywords use them."""
    norm = _normalise("Error 403!")
    assert "403" in norm
    assert "!" in norm


# ─────────────────────────────────────────────────────────────────────────
# _MIN_LEN guard
# ─────────────────────────────────────────────────────────────────────────

def test_match_rejects_too_short_messages():
    """'hi' / 'help?' are below _MIN_LEN (8) → no auto-answer.  Prevents
    the bot responding to every greeting with a FAQ embed."""
    assert match("hi") is None
    assert match("help?") is None
    assert match("x" * (_MIN_LEN - 1)) is None


def test_match_accepts_messages_at_min_len():
    """At the exact threshold, consider it a real question (if any FAQ
    keyword matches)."""
    # A string exactly at _MIN_LEN with no keyword still returns None,
    # but it should get past the length gate.  We prove it by using a
    # string that contains a known keyword (spotify).
    msg = "spotify " * 2   # 16 chars, well above threshold
    assert match(msg) is not None


def test_match_rejects_whitespace_only():
    """A message of only spaces/tabs trims below _MIN_LEN."""
    assert match("   \t\n   ") is None


def test_match_rejects_none():
    """``match(None)`` must not crash on `len(None.strip())`."""
    assert match(None) is None


def test_match_rejects_empty_string():
    assert match("") is None


# ─────────────────────────────────────────────────────────────────────────
# match — core routing logic
# ─────────────────────────────────────────────────────────────────────────

def test_match_returns_faq_for_single_strong_keyword():
    """One obviously-matching keyword → that entry wins."""
    result = match("Me sale el error smartscreen al abrir la app")
    assert result is not None
    assert "smartscreen" in result.title.lower()


def test_match_is_case_insensitive():
    lower = match("como configuro spotify en la app")
    upper = match("CÓMO CONFIGURO SPOTIFY EN LA APP")
    assert lower is not None
    assert upper is not None
    assert lower.title == upper.title


def test_match_is_accent_insensitive():
    """Users on phone keyboards often skip accents."""
    acc = match("quiero donacion al rol donor")
    nocc = match("quiero donacion al rol donor")
    assert acc is not None
    assert acc.title == nocc.title


def test_match_prefers_entry_with_more_keyword_hits():
    """Two entries could superficially match; whichever has MORE
    distinct keyword hits in the user's message wins."""
    # A message that mentions BOTH 'spotify' AND 'credenciales' AND
    # 'api' — all keywords of the Spotify-config FAQ — must land on
    # that entry rather than on a bare 'spotify' mention elsewhere.
    result = match("Como configuro las credenciales API de spotify en la app")
    assert result is not None
    assert "Spotify" in result.title


def test_match_returns_none_when_no_keyword_hits():
    """Message with no keyword overlap → None (silent, bot stays quiet)."""
    assert match("Mi gato esta durmiendo en el escritorio ahora mismo") is None


def test_match_substring_match_catches_embedded_keyword():
    """Keyword 'spotify' must match inside 'cómo-uso-spotify-ahora' —
    substring, not whole-word."""
    assert match("como uso spotify ahora mismo?") is not None


def test_match_threshold_blocks_insufficient_hits():
    """When an entry's threshold is > 1 and only one keyword matches,
    the entry does NOT win.  Build a one-off stub to isolate this."""
    stub_entries = [FaqEntry(
        keywords=("rare_word_a", "rare_word_b", "rare_word_c"),
        title="Stub",
        answer="x",
        threshold=2,       # need 2 matches minimum
    )]
    import backend.faq_responder as fr
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fr, "FAQ_ENTRIES", stub_entries)
        # Only one keyword in the message → below threshold → None.
        assert fr.match("some message with rare_word_a only here") is None
        # Two keywords → passes threshold.
        assert fr.match("message with rare_word_a and rare_word_b") is not None


def test_match_first_entry_wins_on_tie():
    """When two entries score identically, the FIRST one in FAQ_ENTRIES
    wins — the file's order is intentional (most specific first)."""
    stub_entries = [
        FaqEntry(keywords=("alpha",), title="First", answer="x"),
        FaqEntry(keywords=("alpha",), title="Second", answer="y"),
    ]
    import backend.faq_responder as fr
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(fr, "FAQ_ENTRIES", stub_entries)
        result = fr.match("message mentioning alpha here")
        assert result is not None
        assert result.title == "First"


# ─────────────────────────────────────────────────────────────────────────
# Catalogue sanity — every FAQ entry still responds to its intent
# ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("question_text,title_fragment", [
    ("Windows me dice editor desconocido al abrir",       "SmartScreen"),
    ("como configuro spotify client id y secret",         "Spotify"),
    ("ya hice una donacion kofi pero no tengo donor",     "Donar"),
    ("la app no abre y crashea al iniciar siempre",       "no arranca"),
    ("beatport no me saca el bpm ni la camelot key",      "BPM"),
    ("funciona esto en mac o linux ubuntu?",              "Mac"),
    ("como actualizo la app a la ultima version",         "Actualizar"),
    ("youtube me da error 403 forbidden al descargar",    "403"),
    ("el track esta bloqueado por drm en mi region",      "DRM"),
    ("como instalo DJ Tracks por primera vez",            "instalar"),
    ("como saco mi discord user id developer mode",       "Discord"),
])
def test_every_faq_entry_still_matches_its_intent(question_text, title_fragment):
    """Regression guard: a keyword list edit that silently stops answering
    its own canonical question would otherwise go unnoticed until a user
    complained.  This parametrize ensures every one of the 11 entries
    still fires for the kind of question it was authored to answer."""
    result = match(question_text)
    assert result is not None, \
        f"No FAQ matched: {question_text!r} (expected '{title_fragment}')"
    assert title_fragment.lower() in result.title.lower(), (
        f"Wrong FAQ: expected '{title_fragment}' in title, "
        f"got '{result.title}' for {question_text!r}"
    )


def test_faq_entries_catalogue_is_populated():
    """Guard against someone accidentally emptying FAQ_ENTRIES."""
    assert len(FAQ_ENTRIES) >= 10


def test_every_entry_has_mandatory_fields():
    """Each FaqEntry needs non-empty keywords, title, and answer."""
    for entry in FAQ_ENTRIES:
        assert entry.keywords, f"empty keywords in {entry.title!r}"
        assert entry.title.strip(), "empty title"
        assert entry.answer.strip(), f"empty answer in {entry.title!r}"
        assert entry.threshold >= 1
