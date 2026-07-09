"""Unit tests for distinctive-token extraction and project display naming (Phase 2C.5)."""
from app.memory import tokens


def test_drops_stopwords_and_boilerplate():
    out = tokens.distinctive_tokens("Re: Fwd: quick meeting about the ARISE onboarding")
    assert "arise" in out
    assert "onboarding" in out
    assert "meeting" not in out
    assert "the" not in out
    assert "quick" not in out


def test_dedupes_and_lowercases():
    out = tokens.distinctive_tokens("ARISE arise Arise robotics")
    assert out.count("arise") == 1
    assert "robotics" in out


def test_drops_pure_numbers_and_short_tokens():
    out = tokens.distinctive_tokens("2026 hi ok robotics")
    assert "2026" not in out
    assert "hi" not in out  # stopword
    assert "ok" not in out  # too short, not a kept acronym
    assert "robotics" in out


def test_keeps_known_short_acronyms():
    assert "ai" in tokens.distinctive_tokens("building an ai model")


def test_display_name_uppercases_acronyms():
    assert tokens.display_name("arise") == "ARISE"
    assert tokens.display_name("union") == "UNION"


def test_display_name_titlecases_long_tokens():
    assert tokens.display_name("robotics") == "Robotics"
