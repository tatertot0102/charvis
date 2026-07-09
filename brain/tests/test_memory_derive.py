"""Unit tests for memory derivation — pure, no DB (Phase 2C.5)."""
from datetime import UTC, datetime, timedelta

from app.memory import derive
from app.memory.signals import (
    CaptureSignal,
    EmailSignal,
    EventSignal,
    PersonSignal,
    Signals,
    TelegramSignal,
    WaitingSignal,
)

NOW = datetime(2026, 7, 9, 18, 0, tzinfo=UTC)


def _email(**kw) -> EmailSignal:
    base = dict(
        gmail_id="m", thread_id="t", subject="", snippet="", from_email="x@arise.org",
        from_name="X", to_emails=("me@example.com",), direction="inbound", received_at=NOW,
        is_promotional=False, requires_response=False, is_deadline_related=False,
    )
    base.update(kw)
    return EmailSignal(**base)


def _arise_signals() -> Signals:
    emails = [
        _email(gmail_id=f"a{i}", thread_id=f"ta{i}", subject="ARISE onboarding update",
               from_email="priya@arise.org", from_name="Priya")
        for i in range(4)
    ]
    events = [
        EventSignal(event_id=f"e{i}", summary="ARISE lab meeting", start=NOW + timedelta(days=i),
                    location="Room 200", attendees=("priya@arise.org",), description="research")
        for i in range(3)
    ]
    captures = [CaptureSignal(id=1, text="finish ARISE dataset", created_at=NOW)]
    telegram = [TelegramSignal(id=1, text="been heads down on ARISE this week", created_at=NOW)]
    people = [PersonSignal(email="priya@arise.org", name="Priya", message_count=6,
                           last_inbound_at=NOW, last_outbound_at=NOW, last_interaction_at=NOW)]
    return Signals(account="default", now=NOW, emails=emails, events=events,
                   captures=captures, telegram=telegram, people=people, waiting=[])


def test_derive_projects_finds_arise_with_evidence():
    projects = derive.derive_projects(_arise_signals())
    arise = next((p for p in projects if p.subject == "ARISE"), None)
    assert arise is not None
    # Evidence spans multiple sources → high confidence and an explainable statement.
    assert arise.confidence >= 0.8
    assert set(arise.evidence.by_source) >= {"gmail", "calendar", "capture", "telegram"}
    assert "Research" in arise.contexts  # overlapping context tag


def test_promotional_email_never_becomes_a_project():
    signals = Signals(
        account="default", now=NOW,
        emails=[_email(gmail_id=f"p{i}", thread_id=f"tp{i}", subject="LinkedIn: new job matches",
                       from_email="jobs@linkedin.com", is_promotional=True) for i in range(10)],
    )
    projects = derive.derive_projects(signals)
    assert all("linkedin" not in p.subject.lower() for p in projects)


def test_single_weak_source_is_not_a_project():
    signals = Signals(
        account="default", now=NOW,
        emails=[_email(gmail_id="s1", thread_id="ts1", subject="Zephyr note")],  # 1 mention only
    )
    assert derive.derive_projects(signals) == []


def test_derive_people_flags_important_contact():
    people = derive.derive_people(_arise_signals())
    priya = next((p for p in people if p.subject == "priya@arise.org"), None)
    assert priya is not None
    assert priya.kind == "person"
    assert "Research" in priya.contexts or "School" in priya.contexts  # .org → subjects-based


def test_derive_commitments_from_waiting_and_captures():
    signals = Signals(
        account="default", now=NOW,
        emails=[_email(gmail_id="d1", thread_id="td1", subject="Grant due Friday",
                       is_deadline_related=True)],
        captures=[CaptureSignal(id=9, text="call the dentist", created_at=NOW)],
        waiting=[WaitingSignal(kind="waiting_on_me", thread_id="tw1", person_email="dana@lab.org",
                               subject="Budget question", last_message_at=NOW,
                               follow_up_recommended=False)],
    )
    commitments = derive.derive_commitments(signals)
    directions = {c.direction for c in commitments}
    assert "owed_by_me" in directions  # the reply I owe + the captured task
    assert "deadline" in directions
    assert any("dentist" in c.description for c in commitments)
    assert any(c.dedupe_key == "waiting:tw1" for c in commitments)


def test_derive_top_level_returns_all_kinds():
    memory = derive.derive(_arise_signals())
    kinds = {c.kind for c in memory.conclusions}
    assert "project" in kinds
    assert "person" in kinds
