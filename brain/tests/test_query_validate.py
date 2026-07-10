"""Unit tests for the hardened LLM-fallback validator (Phase 2D.3)."""
from app.conversation import truth_guard
from app.query import validate
from app.sources.registry import CALENDAR, GMAIL, SourceReport, SourceStatus


def _reports(*, gmail=SourceStatus.CONNECTED, calendar=SourceStatus.CONNECTED):
    return {
        GMAIL: SourceReport(name=GMAIL, status=gmail, detail=""),
        CALENDAR: SourceReport(name=CALENDAR, status=calendar, detail=""),
    }


def test_flags_email_denial_when_connected():
    reply = "I'm sorry, I can't access your email."
    assert validate.falsely_denies(reply, _reports()) == GMAIL
    assert validate.sanitize_fallback(reply, reports=_reports()) == validate.SAFE_EMAIL_REPLY


def test_allows_email_denial_when_actually_disconnected():
    reply = "I can't access your email."
    assert validate.falsely_denies(reply, _reports(gmail=SourceStatus.DISCONNECTED)) is None
    # Truthful denial passes through untouched (truth_guard also leaves it alone).
    out = validate.sanitize_fallback(reply, reports=_reports(gmail=SourceStatus.DISCONNECTED))
    assert out == reply


def test_flags_calendar_denial_when_connected():
    reply = "I don't have access to your calendar."
    assert validate.sanitize_fallback(reply, reports=_reports()) == validate.SAFE_CALENDAR_REPLY


def test_empty_result_is_not_a_capability_denial():
    reply = "I couldn't find any events in your email."
    assert validate.falsely_denies(reply, _reports()) is None
    assert validate.sanitize_fallback(reply, reports=_reports()) == reply


def test_normal_reply_passes_through():
    reply = "Sure — your next meeting is at 3pm."
    assert validate.sanitize_fallback(reply, reports=_reports()) == reply


def test_still_blocks_placeholder_and_false_write_claims():
    placeholder = "Here's your week: [insert existing events]"
    assert validate.sanitize_fallback(placeholder, reports=_reports()) == truth_guard.SAFE_REPLY
    false_write = "Done! I've updated your calendar with the new event."
    assert validate.sanitize_fallback(false_write, reports=_reports()) == truth_guard.SAFE_REPLY
