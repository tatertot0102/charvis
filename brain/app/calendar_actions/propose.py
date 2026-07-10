"""Turn a parsed request into a drafted, confirmable proposal (Phase 2D / 2D.1) — never a write.

"Combine, don't guess" meets the confirmation rule: resolve target event(s) with confidence, compute
the exact change, detect conflicts, and draft a pending action whose summary cites provider-backed
evidence. Outputs are only a PROPOSED action awaiting confirmation, or a CLARIFY/NONE message. It
NEVER calls the write connector and NEVER invents an event — every proposed item is a real
CalendarEvent returned by Google. Execution is a separate, confirmation-gated step (execute.py).

Bulk requests ("delete all future DSI events") draft one action over the whole matched set and
require the stronger "CONFIRM DELETE" / "CONFIRM MOVE" phrase so a plain CONFIRM can't fire them.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar_actions import conflicts, resolve, store
from app.calendar_actions.schema import (
    ActionType,
    Outcome,
    ParsedRequest,
    ProposalOutcome,
    Resolution,
    ScoredEvent,
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


def _pct(confidence: float) -> str:
    return f"{round(confidence * 100)}%"


def _conflict_note(items: list) -> str:
    if not items:
        return ""
    names = ", ".join(f"“{e.summary}” ({_fmt_time(e.start)})" for e in items[:3])
    return f"\n⚠️ Heads up — this overlaps: {names}."


async def _search_events(request: ParsedRequest, account: str) -> list:
    """The provider-backed pool to match against — wide lookback/lookahead (Phase 2D.1).

    Bulk 'future' requests search from the start of today forward; single requests also look a little
    back so 'my 3pm' still resolves earlier today. Nothing here is fabricated — all events come from
    Google Calendar.
    """
    settings = get_settings()
    tz = _tz()
    now = datetime.now(tz)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=tz)
    back = start_of_today if request.bulk else now - timedelta(
        days=settings.calendar_action_lookback_days
    )
    forward = now + timedelta(days=settings.calendar_action_lookahead_days)
    return await calendar.list_events_range(back, forward, account=account)


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


# --- create -------------------------------------------------------------------


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


# --- update / delete (single + bulk) -----------------------------------------


def _ambiguous_text(verb: str, matches: tuple[ScoredEvent, ...]) -> str:
    lines = ["I found a few events that match — which one did you mean?"]
    for scored in matches[:6]:
        event = scored.event
        lines.append(f"• {event.summary} — {_fmt_when(event.start)} ({_pct(scored.confidence)})")
    lines.append(f"Tell me the exact name or time and I'll draft the {verb}.")
    return "\n".join(lines)


def _no_match_text(request: ParsedRequest, verb: str) -> str:
    what = request.attendee_hint or request.target_hint or "that"
    return (
        f"I couldn't find any {'future ' if request.bulk else ''}events matching “{what}”. "
        "I won't guess — tell me the exact name, time, or attendee."
    )


async def _propose_change(
    request: ParsedRequest, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    is_move = request.action_type is ActionType.UPDATE
    verb = "move" if is_move else "cancel"
    if is_move and request.new_time is None:
        return ProposalOutcome(Outcome.CLARIFY, "What time should I move it to?")
    if not (request.target_hint or request.attendee_hint or request.target_time):
        return ProposalOutcome(
            Outcome.CLARIFY, f"Which event should I {verb}? Name it, or give its time or attendee."
        )

    settings = get_settings()
    events = await _search_events(request, account)
    result = resolve.resolve(request, events, min_confidence=settings.calendar_action_min_confidence)

    if result.resolution is Resolution.NONE:
        return ProposalOutcome(Outcome.NONE, _no_match_text(request, verb))
    if result.resolution is Resolution.BULK:
        return await _draft_bulk(request, result.matches, channel, external_id, account)
    if result.resolution is Resolution.AMBIGUOUS:
        return ProposalOutcome(Outcome.CLARIFY, _ambiguous_text(verb, result.matches))

    scored = result.top
    if is_move:
        return await _draft_move(request, scored, channel, external_id, account)
    return await _draft_delete(scored, channel, external_id, account)


def _evidence_line(scored: ScoredEvent) -> str:
    return "; ".join(scored.reasons) if scored.reasons else "matched your request"


async def _draft_move(
    request: ParsedRequest, scored: ScoredEvent, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    event = scored.event
    tz = event.start.tzinfo
    base_day = (
        (datetime.now(tz) + timedelta(days=request.day_offset)).date()
        if request.day_offset is not None
        else event.start.date()
    )
    new_start = _combine(base_day, request.new_time, tz)
    new_end = new_start + (event.end - event.start)

    found = await conflicts.conflicts_for(
        new_start, new_end, exclude_event_id=event.event_id, account=account
    )
    summary = (
        f'Move “{event.summary}” from {_fmt_when(event.start)} to {_fmt_when(new_start)} '
        f"(confidence {_pct(scored.confidence)}; {_evidence_line(scored)})." + _conflict_note(found)
    )
    payload = {
        "target_event_id": event.event_id,
        "summary": event.summary,
        "old_start": event.start.isoformat(),
        "start": new_start.isoformat(),
        "end": new_end.isoformat(),
        "reasons": list(scored.reasons),
    }
    row = await store.draft(
        action_type=ActionType.UPDATE,
        summary=summary,
        payload=payload,
        target_event_id=event.event_id,
        channel=channel,
        external_id=external_id,
        account=account,
        confidence=scored.confidence,
    )
    return ProposalOutcome(
        Outcome.PROPOSED, summary + CONFIRM_SUFFIX, action_id=row.id, conflicts=tuple(found)
    )


async def _draft_delete(
    scored: ScoredEvent, channel: str, external_id: str | None, account: str
) -> ProposalOutcome:
    event = scored.event
    summary = (
        f'Cancel “{event.summary}” on {_fmt_when(event.start)} '
        f"(confidence {_pct(scored.confidence)}; {_evidence_line(scored)})."
    )
    payload = {
        "target_event_id": event.event_id,
        "summary": event.summary,
        "start": event.start.isoformat(),
        "reasons": list(scored.reasons),
    }
    row = await store.draft(
        action_type=ActionType.DELETE,
        summary=summary,
        payload=payload,
        target_event_id=event.event_id,
        channel=channel,
        external_id=external_id,
        account=account,
        confidence=scored.confidence,
    )
    return ProposalOutcome(Outcome.PROPOSED, summary + CONFIRM_SUFFIX, action_id=row.id)


def _bulk_phrase(action_type: ActionType) -> str:
    return "CONFIRM MOVE" if action_type is ActionType.UPDATE else "CONFIRM DELETE"


def _bulk_preview(matches: tuple[ScoredEvent, ...], limit: int) -> str:
    lines: list[str] = []
    for i, scored in enumerate(matches[:limit], start=1):
        event = scored.event
        lines.append(f"{i}. {event.summary} — {_fmt_when(event.start)} ({_pct(scored.confidence)})")
        for reason in scored.reasons:
            lines.append(f"   • {reason}")
    return "\n".join(lines)


async def _draft_bulk(
    request: ParsedRequest,
    matches: tuple[ScoredEvent, ...],
    channel: str,
    external_id: str | None,
    account: str,
) -> ProposalOutcome:
    settings = get_settings()
    matches = matches[: settings.calendar_bulk_max]
    is_move = request.action_type is ActionType.UPDATE
    verb = "move" if is_move else "delete"
    phrase = _bulk_phrase(request.action_type)
    count = len(matches)

    targets: list[dict] = []
    for scored in matches:
        event = scored.event
        target = {
            "target_event_id": event.event_id,
            "summary": event.summary,
            "start": event.start.isoformat(),
            "confidence": scored.confidence,
            "reasons": list(scored.reasons),
        }
        if is_move:
            tz = event.start.tzinfo
            new_start = _combine(event.start.date(), request.new_time, tz)
            target["new_start"] = new_start.isoformat()
            target["new_end"] = (new_start + (event.end - event.start)).isoformat()
        targets.append(target)

    header = f"I found {count} event{'s' if count != 1 else ''} to {verb}:"
    preview = _bulk_preview(matches, settings.calendar_bulk_preview_count)
    more = f"\n(showing the first {settings.calendar_bulk_preview_count} of {count})" if (
        count > settings.calendar_bulk_preview_count
    ) else ""
    summary = f"{header}\n\n{preview}{more}"
    tail = f"\n\nReply {phrase} to {verb} {'these ' + str(count) if count > 1 else 'this'} event" \
        f"{'s' if count != 1 else ''}, or anything else to hold off."

    min_conf = min(s.confidence for s in matches)
    row = await store.draft(
        action_type=request.action_type,
        summary=summary,
        payload={"targets": targets, "bulk": True, "new_time": (
            request.new_time.isoformat() if request.new_time else None
        )},
        channel=channel,
        external_id=external_id,
        account=account,
        confidence=min_conf,
        required_phrase=phrase,
        item_count=count,
    )
    return ProposalOutcome(Outcome.PROPOSED, summary + tail, action_id=row.id)
