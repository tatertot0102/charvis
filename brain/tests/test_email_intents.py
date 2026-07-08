"""Unit tests for natural-language email intent detection + name extraction."""
import pytest

from app.conversation.intents import EmailIntent, detect_email_intent


@pytest.mark.parametrize(
    "text,intent",
    [
        ("check my email", EmailIntent.UNREAD),
        ("show unread", EmailIntent.UNREAD),
        ("anything important?", EmailIntent.IMPORTANT),
        ("what emails need my attention", EmailIntent.IMPORTANT),
        ("what am I waiting on?", EmailIntent.WAITING),
        ("who owes me a reply", EmailIntent.WAITING),
        ("summarize today's email", EmailIntent.SUMMARIZE),
    ],
)
def test_intent_detection(text, intent):
    result = detect_email_intent(text)
    assert result is not None
    assert result[0] == intent


def test_did_reply_strips_title():
    assert detect_email_intent("did Mr. Brickman reply?") == (EmailIntent.DID_REPLY, "brickman")


def test_did_reply_from_phrasing():
    result = detect_email_intent("any word from Sarah yet?")
    assert result is not None
    assert result[0] == EmailIntent.DID_REPLY
    assert "sarah" in result[1]


def test_did_reply_ignores_pronoun_subject():
    # "did I reply ..." is about me, not a person to look up → not a DID_REPLY lookup.
    result = detect_email_intent("did I reply to everyone")
    assert result is None or result[0] != EmailIntent.DID_REPLY


@pytest.mark.parametrize("text", ["what's the weather", "hello there", "tell me a joke"])
def test_non_email_returns_none(text):
    assert detect_email_intent(text) is None
