"""Unit tests for Phase 2C cross-source context intent detection."""
import pytest

from app.conversation.intents import ContextIntent, detect_context_intent


@pytest.mark.parametrize(
    "text,intent",
    [
        ("prep me for my next meeting", ContextIntent.PREP_MEETING),
        ("get me ready for my meeting", ContextIntent.PREP_MEETING),
        ("what is my next meeting about?", ContextIntent.MEETING_ABOUT),
        ("what's this meeting about", ContextIntent.MEETING_ABOUT),
        ("what emails are related to my next event", ContextIntent.EVENT_EMAILS),
        ("show me emails related to my meeting", ContextIntent.EVENT_EMAILS),
        ("what deadlines are coming up?", ContextIntent.DEADLINES),
        ("what's due soon", ContextIntent.DEADLINES),
        ("what should I do next?", ContextIntent.NEXT_ACTION),
        ("what's my top priority", ContextIntent.NEXT_ACTION),
    ],
)
def test_context_intent_detection(text, intent):
    assert detect_context_intent(text) == intent


def test_meeting_about_beats_prep():
    # "what is my next meeting about" must resolve to MEETING_ABOUT, not PREP_MEETING.
    assert detect_context_intent("what is my next meeting about") == ContextIntent.MEETING_ABOUT


@pytest.mark.parametrize("text", ["hello there", "tell me a joke", "check my email", "what's my day"])
def test_non_context_returns_none(text):
    assert detect_context_intent(text) is None
