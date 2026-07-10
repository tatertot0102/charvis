"""Unit tests for the Phase 2D.3 intent detectors (pure, no DB)."""
import pytest

from app.conversation import intents


# --- ranged schedule queries (R1) -------------------------------------------


@pytest.mark.parametrize(
    "text, key",
    [
        ("what does my month look like", "this_month"),
        ("what do I have next week", "next_week"),
        ("what's on my calendar tomorrow", "tomorrow"),
        ("what am I doing next month", "next_month"),
        ("any plans this weekend", "weekend"),
    ],
)
def test_detect_schedule_range_matches(text, key):
    tr = intents.detect_schedule_range(text)
    assert tr is not None and tr.key == key


def test_detect_schedule_range_ignores_today_and_this_week():
    # These have dedicated handlers; the ranged detector must decline them.
    assert intents.detect_schedule_range("what do I have today") is None
    assert intents.detect_schedule_range("what do I have this week") is None


def test_detect_schedule_range_needs_schedule_intent():
    # A range word without a schedule question is not a schedule read.
    assert intents.detect_schedule_range("remind me next month") is None
    assert intents.detect_schedule_range("email LuAnn next week") is None


# --- calendar verification (R4) ---------------------------------------------


def test_detect_verification_with_subject():
    result = intents.detect_calendar_verification("is the ECE ML lab on my calendar?")
    assert result == (True, "ece ml lab")


def test_detect_verification_bare_reference():
    assert intents.detect_calendar_verification("is this on my Google Calendar?") == (True, None)


def test_declarative_statement_is_not_verification():
    assert intents.detect_calendar_verification("my lab is on my calendar every weekday") is None


def test_calendar_action_is_not_verification():
    assert intents.detect_calendar_verification("add lunch to my calendar") is None


# --- email event search (R3) ------------------------------------------------


def test_detect_email_event_search():
    assert intents.detect_email_event_search("check my email for upcoming events") == (True, None)


def test_detect_email_event_search_with_person():
    result = intents.detect_email_event_search("any event invitations from LuAnn in my email")
    assert result == (True, "luann")


def test_plain_check_email_is_not_event_search():
    # Must still fall through to the unread handler, not the event search.
    assert intents.detect_email_event_search("check my email") is None
    assert intents.detect_email_event_search("summarize my inbox") is None


def test_plain_check_email_routes_to_unread():
    assert intents.detect_email_intent("check my email") == (intents.EmailIntent.UNREAD, None)
