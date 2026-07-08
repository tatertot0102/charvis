"""Unit tests for the deterministic 'what's my day?' intent matcher (no LLM, no DB)."""
import pytest

from app.conversation import intents


@pytest.mark.parametrize(
    "text",
    [
        "what's my day?",
        "whats my day",
        "What is my day looking like",
        "what's on my calendar today?",
        "show me today's schedule",
        "what do I have today",
        "what am I doing today?",
        "what's my agenda",
    ],
)
def test_matches_schedule_queries(text):
    assert intents.is_todays_schedule_query(text) is True


@pytest.mark.parametrize(
    "text",
    [
        "capture: buy milk",
        "what's the weather tomorrow",
        "how are you",
        "remind me to call Sam",
        "what day is it",  # date, not schedule
    ],
)
def test_ignores_unrelated_messages(text):
    assert intents.is_todays_schedule_query(text) is False
