"""Unit tests for behavioral pattern detection — pure, no DB (Phase 2C.5)."""
from datetime import UTC, datetime, timedelta

from app.memory import patterns
from app.memory.signals import EmailSignal, EventSignal, PersonSignal, Signals

NOW = datetime(2026, 7, 9, 18, 0, tzinfo=UTC)


def _email(direction, thread_id, received_at, from_email="dana@lab.org") -> EmailSignal:
    return EmailSignal(
        gmail_id=f"{thread_id}-{direction}", thread_id=thread_id, subject="s", snippet="",
        from_email=from_email if direction == "inbound" else "me@example.com",
        from_name=None, to_emails=("me@example.com",), direction=direction,
        received_at=received_at, is_promotional=False, requires_response=False,
        is_deadline_related=False,
    )


def test_response_time_pattern_needs_two_replies():
    # Two threads: inbound from Dana, then my reply within hours → "usually reply within a day".
    emails = []
    for i in range(2):
        base = NOW + timedelta(days=i)
        emails.append(_email("inbound", f"t{i}", base))
        emails.append(_email("outbound", f"t{i}", base + timedelta(hours=3)))
    signals = Signals(account="default", now=NOW, emails=emails)
    result = patterns.response_time_patterns(signals)
    dana = next((p for p in result if p.subject == "dana@lab.org"), None)
    assert dana is not None
    assert "within a day" in dana.description


def test_single_reply_is_not_a_pattern():
    emails = [_email("inbound", "t0", NOW), _email("outbound", "t0", NOW + timedelta(hours=2))]
    signals = Signals(account="default", now=NOW, emails=emails)
    assert patterns.response_time_patterns(signals) == []


def test_activity_window_pattern_from_clustered_times():
    when = datetime(2026, 7, 5, 20, 0, tzinfo=UTC)  # a specific Sunday evening
    emails = [_email("outbound", f"w{i}", when) for i in range(4)]
    signals = Signals(account="default", now=NOW, emails=emails)
    result = patterns.activity_window_pattern(signals)
    assert result
    assert "Sunday evening" in result[0].subject


def test_activity_window_needs_enough_events():
    emails = [_email("outbound", "w0", datetime(2026, 7, 5, 20, 0, tzinfo=UTC))]
    signals = Signals(account="default", now=NOW, emails=emails)
    assert patterns.activity_window_pattern(signals) == []


def test_recurring_contact_pattern():
    signals = Signals(
        account="default", now=NOW,
        people=[PersonSignal(email="dana@lab.org", name="Dana", message_count=9,
                             last_inbound_at=NOW, last_outbound_at=NOW, last_interaction_at=NOW)],
    )
    result = patterns.recurring_contact_patterns(signals)
    assert result
    assert result[0].subject == "dana@lab.org"
    assert "Dana" in result[0].description


def test_noreply_never_a_recurring_contact():
    signals = Signals(
        account="default", now=NOW,
        people=[PersonSignal(email="no-reply@news.com", name=None, message_count=50,
                             last_inbound_at=NOW, last_outbound_at=None, last_interaction_at=NOW)],
    )
    assert patterns.recurring_contact_patterns(signals) == []


def test_unused_event_signal_import_guard():
    # EventSignal is part of activity-window evidence; ensure the type is importable/constructable.
    assert EventSignal(event_id="e", summary="x", start=NOW, location=None,
                       attendees=(), description="").summary == "x"
