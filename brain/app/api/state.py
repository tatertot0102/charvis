"""Unified state endpoints (Phase 2C) — cross-source reasoning over Calendar + Gmail + ledger.

These endpoints combine the read sources Jarvis already has into single answers, rather than making
callers stitch Calendar and Gmail together themselves. All read-only. Each returns 200 with
connected=False (not an error) when Google isn't authorized, matching /calendar/today and /gmail/*.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends

from app.config import get_settings
from app.context import briefing, deadlines, resolver
from app.coordination import waiting
from app.deps import require_token
from app.integrations.google import calendar, gmail
from app.memory import next_action
from app.schemas import (
    CalendarEventOut,
    DeadlineOut,
    DeadlinesResponse,
    EventBriefingResponse,
    NextActionResponse,
    RelatedEmailOut,
    StateTodayResponse,
    WaitingItemOut,
    WaitingResponse,
)

router = APIRouter(tags=["state"])

_NOT_CONNECTED = "Google is not connected. GET /integrations/google/connect to authorize."


def _event_out(event: calendar.CalendarEvent) -> CalendarEventOut:
    return CalendarEventOut(
        summary=event.summary,
        start=event.start.isoformat(),
        end=event.end.isoformat(),
        all_day=event.all_day,
        location=event.location,
    )


def _waiting_out(item, now: datetime) -> WaitingItemOut:
    days = (now - item.last_message_at).days if item.last_message_at else 0
    return WaitingItemOut(
        kind=item.kind,
        thread_id=item.thread_id,
        person_email=item.person_email,
        subject=item.subject or "",
        last_message_at=item.last_message_at.isoformat() if item.last_message_at else None,
        last_message_direction=item.last_message_direction,
        follow_up_recommended=item.follow_up_recommended,
        days_waiting=max(0, days),
    )


@router.get("/state/today", response_model=StateTodayResponse)
async def state_today(_: None = Depends(require_token)) -> StateTodayResponse:
    """Today's calendar plus a waiting-on overview — the unified 'what's my day' view."""
    tz = get_settings().tz
    try:
        events = await calendar.list_todays_events()
    except calendar.NotConnectedError:
        return StateTodayResponse(connected=False, timezone=tz, detail=_NOT_CONNECTED)

    # Waiting counts are best-effort: Gmail may be unconnected even when Calendar is.
    on_me = on_them = 0
    try:
        items = await waiting.list_waiting()
        on_me = sum(1 for i in items if i.kind == waiting.WAITING_ON_ME)
        on_them = sum(1 for i in items if i.kind == waiting.WAITING_ON_THEM)
    except Exception:  # noqa: BLE001 — never let a ledger read break the day view.
        pass

    timed = [e for e in events if not e.all_day]
    parts = [f"{len(events)} event{'s' if len(events) != 1 else ''} today"]
    if timed:
        parts.append(f"next at {timed[0].start.strftime('%-I:%M %p').lstrip('0')}")
    if on_me:
        parts.append(f"{on_me} awaiting your reply")
    summary = "; ".join(parts) + "."

    return StateTodayResponse(
        connected=True,
        timezone=tz,
        events=[_event_out(e) for e in events],
        waiting_on_me_count=on_me,
        waiting_on_them_count=on_them,
        summary=summary,
    )


@router.get("/state/waiting", response_model=WaitingResponse)
async def state_waiting(_: None = Depends(require_token)) -> WaitingResponse:
    """The waiting-on ledger, split by who owes whom (runs a fresh Gmail sync first)."""
    from app.integrations.google import sync

    try:
        await sync.sync_recent()
    except gmail.NotConnectedError:
        return WaitingResponse(connected=False, detail=_NOT_CONNECTED)
    now = datetime.now(UTC)
    them: list[WaitingItemOut] = []
    me: list[WaitingItemOut] = []
    for item in await waiting.list_waiting():
        (them if item.kind == waiting.WAITING_ON_THEM else me).append(_waiting_out(item, now))
    return WaitingResponse(connected=True, waiting_on_them=them, waiting_on_me=me)


@router.get("/state/deadlines", response_model=DeadlinesResponse)
async def state_deadlines(_: None = Depends(require_token)) -> DeadlinesResponse:
    """Upcoming deadlines aggregated from calendar events + deadline-flagged email."""
    items = await deadlines.aggregate_deadlines()
    if not items:
        # Distinguish 'connected but empty' from 'not connected' via a quick calendar probe.
        try:
            await calendar.list_todays_events()
        except calendar.NotConnectedError:
            return DeadlinesResponse(connected=False, detail=_NOT_CONNECTED)
    return DeadlinesResponse(
        connected=True,
        deadlines=[
            DeadlineOut(
                source=d.source,
                title=d.title,
                when=d.when.isoformat() if d.when else None,
                detail=d.detail,
                urgency=d.urgency,
            )
            for d in items
        ],
    )


@router.get("/state/next-action", response_model=NextActionResponse)
async def state_next_action(_: None = Depends(require_token)) -> NextActionResponse:
    """The single highest-priority thing to do, synthesized across all sources."""
    try:
        context = await resolver.resolve_next_meeting()
    except calendar.NotConnectedError:
        return NextActionResponse(connected=False, detail=_NOT_CONNECTED)
    try:
        items = await waiting.list_waiting()
    except Exception:  # noqa: BLE001
        items = []
    dls = await deadlines.aggregate_deadlines()
    memory_hint = await next_action.suggest_from_memory()
    recommendation = briefing.format_next_action(context, items, dls, memory_hint=memory_hint)
    return NextActionResponse(connected=True, recommendation=recommendation)


@router.get("/state/next-meeting", response_model=EventBriefingResponse)
async def state_next_meeting(_: None = Depends(require_token)) -> EventBriefingResponse:
    """Full briefing for the next meeting: synthesized prose + the related-email evidence."""
    try:
        context = await resolver.resolve_next_meeting()
    except calendar.NotConnectedError:
        return EventBriefingResponse(connected=False, has_event=False, detail=_NOT_CONNECTED)
    if context is None:
        return EventBriefingResponse(
            connected=True, has_event=False, briefing="No upcoming meetings on your calendar."
        )
    text = await briefing.generate_briefing(context)
    related = [
        RelatedEmailOut(
            gmail_id=r.message.gmail_id,
            thread_id=r.message.thread_id,
            from_email=r.message.from_email,
            from_name=r.message.from_name,
            subject=r.message.subject,
            snippet=r.message.snippet,
            received_at=r.message.received_at.isoformat() if r.message.received_at else None,
            is_unread=r.message.is_unread,
            reason=r.reason,
        )
        for r in context.related_emails
    ]
    return EventBriefingResponse(
        connected=True,
        has_event=True,
        event=_event_out(context.event),
        briefing=text,
        related_emails=related,
        waiting_on_me_count=sum(1 for w in context.waiting_items if w.kind == "waiting_on_me"),
    )
