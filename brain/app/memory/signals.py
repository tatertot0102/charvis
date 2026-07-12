"""Raw signal shapes gathered from existing data, fed into the (pure) derivation step.

These are plain, DB-free dataclasses so derivation can be unit-tested without a database. `gather.py`
builds `Signals` from the DB + a best-effort calendar read; `derive.py` consumes it.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class EmailSignal:
    gmail_id: str
    thread_id: str
    subject: str
    snippet: str
    from_email: str
    from_name: str | None
    to_emails: tuple[str, ...]
    direction: str  # inbound | outbound
    received_at: datetime | None
    is_promotional: bool
    requires_response: bool
    is_deadline_related: bool


@dataclass(frozen=True)
class EventSignal:
    event_id: str
    summary: str
    start: datetime | None
    location: str | None
    attendees: tuple[str, ...]
    description: str
    end: datetime | None = None  # for routine time-window phrasing (Phase 2D.4)


@dataclass(frozen=True)
class CaptureSignal:
    id: int
    text: str
    created_at: datetime | None


@dataclass(frozen=True)
class TelegramSignal:
    id: int
    text: str
    created_at: datetime | None


@dataclass(frozen=True)
class PersonSignal:
    email: str
    name: str | None
    message_count: int
    last_inbound_at: datetime | None
    last_outbound_at: datetime | None
    last_interaction_at: datetime | None


@dataclass(frozen=True)
class WaitingSignal:
    kind: str  # waiting_on_them | waiting_on_me
    thread_id: str
    person_email: str | None
    subject: str
    last_message_at: datetime | None
    follow_up_recommended: bool


@dataclass
class Signals:
    """All the raw material one consolidation run reasons over."""

    account: str
    now: datetime
    emails: list[EmailSignal] = field(default_factory=list)
    events: list[EventSignal] = field(default_factory=list)
    captures: list[CaptureSignal] = field(default_factory=list)
    telegram: list[TelegramSignal] = field(default_factory=list)
    people: list[PersonSignal] = field(default_factory=list)
    waiting: list[WaitingSignal] = field(default_factory=list)
