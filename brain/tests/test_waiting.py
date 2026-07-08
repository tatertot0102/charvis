"""Unit tests for waiting-on thread analysis (pure, no network/DB)."""
from datetime import UTC, datetime, timedelta

from app.coordination import waiting
from tests.gmail_helpers import MY_EMAIL, msg

NOW = datetime(2026, 7, 20, 12, 0, tzinfo=UTC)


def test_waiting_on_them_when_i_sent_last_and_stale():
    thread = [
        msg(
            from_email=MY_EMAIL, to=("bob@example.com",), thread_id="tX",
            received_at=NOW - timedelta(days=6),
        )
    ]
    analysis = waiting.analyze_thread(thread, MY_EMAIL, followup_days=4, now=NOW)
    assert analysis.kind == waiting.WAITING_ON_THEM
    assert analysis.person_email == "bob@example.com"
    assert analysis.follow_up_recommended is True


def test_no_followup_when_recent():
    thread = [msg(from_email=MY_EMAIL, to=("bob@example.com",), received_at=NOW - timedelta(days=1))]
    analysis = waiting.analyze_thread(thread, MY_EMAIL, followup_days=4, now=NOW)
    assert analysis.kind == waiting.WAITING_ON_THEM
    assert analysis.follow_up_recommended is False


def test_waiting_on_me_when_they_ask():
    thread = [
        msg(
            from_email="bob@example.com", to=(MY_EMAIL,), subject="Q",
            snippet="can you review?", received_at=NOW - timedelta(days=2),
        )
    ]
    analysis = waiting.analyze_thread(thread, MY_EMAIL, now=NOW)
    assert analysis.kind == waiting.WAITING_ON_ME
    assert analysis.person_email == "bob@example.com"


def test_none_for_promotional_inbound():
    thread = [
        msg(
            from_email="deals@shop.com", labels=("INBOX", "CATEGORY_PROMOTIONS"),
            snippet="can you buy now?", received_at=NOW,
        )
    ]
    assert waiting.analyze_thread(thread, MY_EMAIL, now=NOW) is None


def test_none_for_inbound_fyi():
    thread = [
        msg(from_email="bob@example.com", to=(MY_EMAIL,), subject="notes",
            snippet="sharing the deck", received_at=NOW)
    ]
    assert waiting.analyze_thread(thread, MY_EMAIL, now=NOW) is None


def test_none_for_empty_thread():
    assert waiting.analyze_thread([], MY_EMAIL) is None
