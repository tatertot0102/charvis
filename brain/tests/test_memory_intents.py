"""Unit tests for memory-introspection intent detection (Phase 2C.5)."""
import pytest

from app.conversation.intents import (
    MemoryIntent,
    detect_context_intent,
    detect_memory_intent,
)


@pytest.mark.parametrize(
    "text,expected",
    [
        ("what do you know about me?", MemoryIntent.KNOW_ABOUT_ME),
        ("tell me what you know", MemoryIntent.KNOW_ABOUT_ME),
        ("what patterns have you noticed?", MemoryIntent.PATTERNS),
        ("noticed any patterns?", MemoryIntent.PATTERNS),
        ("what projects do you think I'm working on?", MemoryIntent.PROJECTS),
        ("what am I working on?", MemoryIntent.PROJECTS),
        ("show low confidence conclusions", MemoryIntent.LOW_CONFIDENCE),
        ("what are you unsure about?", MemoryIntent.LOW_CONFIDENCE),
    ],
)
def test_memory_intents_detected(text, expected):
    result = detect_memory_intent(text)
    assert result is not None
    assert result[0] is expected


@pytest.mark.parametrize(
    "text,subject",
    [
        ("why do you think ARISE is important?", "arise"),
        ("why does Dana matter?", "dana"),
        ("why is ARISE important", "arise"),
        ("why do you think Dana is important to me", "dana"),
    ],
)
def test_why_extracts_subject(text, subject):
    result = detect_memory_intent(text)
    assert result is not None
    assert result[0] is MemoryIntent.WHY
    assert result[1] == subject


def test_non_memory_text_returns_none():
    assert detect_memory_intent("what's my day?") is None
    assert detect_memory_intent("send an email to bob") is None


def test_memory_and_context_intents_do_not_collide():
    # "what should I do next" is a context (next-action) intent, not a memory one.
    assert detect_memory_intent("what should I do next?") is None
    assert detect_context_intent("what should I do next?") is not None
