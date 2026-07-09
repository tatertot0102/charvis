"""Turn a parsed request into a drafted, confirmable proposal (Phase 2D) — never a write.

This is where "combine, don't guess" meets the confirmation rule: resolve the target event, compute
the exact change, detect conflicts, and draft a pending action with a human-readable summary. The
only outputs are a PROPOSED action awaiting CONFIRM, or a CLARIFY/NONE message. It NEVER calls the
write connector — execution is a separate, confirmation-gated step (app.calendar_actions.execute).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar_actions import conflicts, store
from app.calendar_actions.resolve import resolve_target
from app.calendar_actions.schema import (
    ActionType,
    Outcome,
    ParsedRequest,
    ProposalOutcome,
    Resolution,
)
from app.config import get_settings
from app.integrations.google import calendar
from app.telemetry import get_logger

log = get_logger(__name__)

CONFIRM_SUFFIX = "\n\nReply CONFIRM to apply this, or anything else to hold off."


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _fmt_time(dt: datetime) -> str:
    return dt.strftime("%-I:%M %p").lstrip("0")


def _fmt_when(dt: datetime) -> str:
    return dt.strftime("%a %b %-d, ") + _fmt_time(dt)


def _combine(day: date, t: time, tzinfo) -> datetime:
    return datetime.combine(day, t, tzinfo=tzinfo)


def _conflict_note(items: list) -> str:
    if not items:
        return ""
    names = ", ".join(f"“{e.summary}” ({_fmt_time(e.start)})" for e in items[:3])
    return f"\n⚠️ Heads up — this overlaps: {names}."


async def _window_events(account: str) -> list:
    """Events from the start of today through the upcoming window — the pool to match against."""
    tz = _tz()
    now = datetime.now(tz)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=tz)
    forward = now + timedelta(days=get_settings().upcoming_window_days)
    return await calendar.list_events_range(start_of_today, forward, account=account)


async def build(
    request: ParsedRequest,
    *,
    channel: str = "telegram",
    external_id: str | None = None,
    account: str = "default",
) -> ProposalOutcome:
    """Draft a proposal for a parsed request. Read-only until (and unless) the user confirms."""
    try:
        if request.action_type is ActionType.CREATE:
            return await _propose_create(request, channel, external_id, account)
        return await _propose_change(request, channel, external_id, account)
    except calendar.NotConnectedError:
        return ProposalOutcome(
            Outcome.NOT_CONNECTED,
            "I'm not connected to your Google Calendar yet. Send /connect_google first.",
        )


async def _propose_create(
    request: ParsedRequest, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    if not request.title:
        return ProposalOutcome(Outcome.CLARIFY, "What should I call the event?")
    if request.new_time is None:
        return ProposalOutcome(
            Outcome.CLARIFY, f"When should I schedule “{request.title}”? Give me a day and time."
        )
    tz = _tz()
    day = (datetime.now(tz) + timedelta(days=request.day_offset or 0)).date()
    start = _combine(day, request.new_time, tz)
    duration = request.duration_minutes or get_settings().default_event_duration_minutes
    end = start + timedelta(minutes=duration)

    found = await conflicts.conflicts_for(start, end, account=account)
    summary = (
        f'Create “{request.title}” on {_fmt_when(start)}–{_fmt_time(end)}.' + _conflict_note(found)
    )
    payload = {
        "summary": request.title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": None,
    }
    row = await store.draft(
        action_type=ActionType.CREATE,
        summary=summary,
        payload=payload,
        channel=channel,
        external_id=external_id,
        account=account,
    )
    return ProposalOutcome(
        Outcome.PROPOSED, summary + CONFIRM_SUFFIX, action_id=row.id, conflicts=tuple(found)
    )


def _ambiguous_text(verb: str, candidates: tuple) -> str:
    lines = [f"I found a few events I could {verb} — which one?"]
    for event in candidates[:6]:
        lines.append(f"• {event.summary} at {_fmt_time(event.start)}")
    lines.append("Tell me the name or time and I'll draft it.")
    return "\n".join(lines)


async def _propose_change(
    request: ParsedRequest, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    is_move = request.action_type is ActionType.UPDATE
    verb = "move" if is_move else "cancel"
    if is_move and request.new_time is None:
        return ProposalOutcome(Outcome.CLARIFY, "What time should I move it to?")

    events = await _window_events(account)
    result = resolve_target(request, events)

    if result.resolution is Resolution.AMBIGUOUS:
        return ProposalOutcome(Outcome.CLARIFY, _ambiguous_text(verb, result.candidates))
    if result.resolution is Resolution.NONE:
        return ProposalOutcome(
            Outcome.NONE,
            f"I couldn't find a meeting to {verb} matching that. "
            "Try naming it or giving its time.",
        )

    event = result.event
    if is_move:
        return await _draft_move(request, event, channel, external_id, account)
    return await _draft_delete(event, channel, external_id, account)


async def _draft_move(
    request: ParsedRequest, event, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    tz = event.start.tzinfo
    base_day = (
        (datetime.now(tz) + timedelta(days=request.day_offset)).date()
        if request.day_offset is not None
        else event.start.date()
    )
    new_start = _combine(base_day, request.new_time, tz)
    duration = event.end - event.start
    new_end = new_start + duration

    found = await conflicts.conflicts_for(
        new_start, new_end, exclude_event_id=event.event_id, account=account
    )
    summary = (
        f'Move “{event.summary}” from {_fmt_when(event.start)} to {_fmt_when(new_start)}.'
        + _conflict_note(found)
    )
    payload = {
        "target_event_id": event.event_id,
        "summary": event.summary,
        "old_start": event.start.isoformat(),
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
    }
    row = await store.draft(
        action_type=ActionType.UPDATE,
        summary=summary,
        payload=payload,
        target_event_id=event.event_id,
        channel=channel,
        external_id=external_id,
        account=account,
    )
    return ProposalOutcome(
        Outcome.PROPOSED, summary + CONFIRM_SUFFIX, action_id=row.id, conflicts=tuple(found)
    )


async def _draft_delete(
    event, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    summary = f'Cancel “{event.summary}” on {_fmt_when(event.start)}.'
    payload = {"target_event_id": event.event_id, "summary": event.summary}
    row = await store.draft(
        action_type=ActionType.DELETE,
        summary=summary,
        payload=payload,
        target_event_id=event.event_id,
        channel=channel,
        external_id=external_id,
        account=account,
    )
    return ProposalOutcome(Outcome.PROPOSED, summary + CONFIRM_SUFFIX, action_id=row.id)
