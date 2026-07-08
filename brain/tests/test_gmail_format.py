"""Unit tests for Gmail chat-text formatting (pure)."""
from datetime import UTC, datetime, timedelta

from app.db.models import WaitingItem
from app.integrations.google import gmail_format
from tests.gmail_helpers import MY_EMAIL, msg


def test_format_unread_empty():
    assert "No unread" in gmail_format.format_unread([], MY_EMAIL)


def test_format_unread_lists_sender_and_subject():
    message = msg(labels=("INBOX", "UNREAD"), from_name="Bob", subject="Hello")
    out = gmail_format.format_unread([message], MY_EMAIL)
    assert "Bob" in out
    assert "Hello" in out


def test_format_important_excludes_promotional():
    promo = msg(labels=("INBOX", "CATEGORY_PROMOTIONS"), subject="Big Sale")
    urgent = msg(subject="Contract due asap", snippet="deadline asap please review")
    out = gmail_format.format_important([promo, urgent], MY_EMAIL)
    assert "Big Sale" not in out
    assert "Contract due asap" in out


def test_format_summary_counts_messages():
    out = gmail_format.format_summary([msg(labels=("INBOX", "UNREAD"))], MY_EMAIL)
    assert "1 message" in out


def test_format_waiting_empty():
    assert "not waiting" in gmail_format.format_waiting([], datetime.now(UTC)).lower()


def test_format_waiting_lists_and_flags_followup():
    item = WaitingItem(
        kind="waiting_on_them",
        thread_id="t1",
        person_email="bob@x.com",
        subject="Proposal",
        last_message_at=datetime.now(UTC) - timedelta(days=5),
        last_message_direction="outbound",
        follow_up_recommended=True,
    )
    out = gmail_format.format_waiting([item], datetime.now(UTC))
    assert "bob@x.com" in out
    assert "follow up" in out


def test_format_did_reply_yes_and_no():
    message = msg(from_name="Brickman", subject="Re: contract",
                  received_at=datetime(2026, 7, 7, tzinfo=UTC))
    assert "Yes" in gmail_format.format_did_reply("brickman", [message], MY_EMAIL)
    assert "No" in gmail_format.format_did_reply("ghost", [], MY_EMAIL)
