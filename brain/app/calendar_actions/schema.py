"""Value types shared across the calendar-actions layer (Phase 2D). No I/O here."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import time
from enum import Enum


class ActionType(str, Enum):
    CREATE = "create"
    UPDATE = "update"  # move / reschedule an existing event
    DELETE = "delete"  # cancel an existing event


class ActionStatus(str, Enum):
    PENDING = "pending"
    EXECUTED = "executed"
    CANCELLED = "cancelled"
    EXPIRED = "expired"
    SUPERSEDED = "superseded"
    FAILED = "failed"


@dataclass(frozen=True)
class ParsedRequest:
    """What we deterministically extracted from the user's message. Pure/testable."""

    action_type: ActionType
    target_hint: str | None = None  # keyword to match an existing event (update/delete)
    target_time: time | None = None  # e.g. "my 3pm" → 15:00, to disambiguate the target event
    new_time: time | None = None  # new start-of-day time (update/create)
    day_offset: int | None = None  # 0=today, 1=tomorrow, … (create/update day)
    title: str | None = None  # event title (create)
    duration_minutes: int | None = None  # explicit duration (create)


class Resolution(str, Enum):
    SINGLE = "single"
    AMBIGUOUS = "ambiguous"
    NONE = "none"


@dataclass(frozen=True)
class ResolveResult:
    """Outcome of matching a request against the calendar. Pure/testable."""

    resolution: Resolution
    event: object | None = None  # a CalendarEvent when resolution is SINGLE
    candidates: tuple = ()  # CalendarEvents when AMBIGUOUS (for the clarifying question)


class Outcome(str, Enum):
    PROPOSED = "proposed"  # a pending action was drafted; awaiting CONFIRM
    CLARIFY = "clarify"  # ambiguous/unparseable — asked a question, nothing drafted
    NONE = "none"  # nothing to act on (e.g. no matching event)
    NOT_CONNECTED = "not_connected"
    ERROR = "error"


@dataclass(frozen=True)
class ProposalOutcome:
    """Result of a propose() call — carries the user-facing text and any drafted action id."""

    outcome: Outcome
    text: str
    action_id: int | None = None
    conflicts: tuple = field(default=())  # CalendarEvents the proposal would collide with
