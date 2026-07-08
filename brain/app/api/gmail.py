"""Read-only Gmail endpoints (Phase 2B).

All endpoints classify live and return 200 with connected=False (not an error) when Google isn't
authorized yet — same pattern as /calendar/today. /gmail/waiting runs a fresh sync so the ledger
reflects current state. Nothing here can modify Gmail.
"""
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query

from app.config import get_settings
from app.coordination import waiting
from app.db.models import WaitingItem
from app.deps import require_token
from app.integrations.google import gmail, sync
from app.integrations.google.classify import Classification, classify
from app.integrations.google.gmail import GmailMessage
from app.schemas import (
    EmailMessageOut,
    GmailListResponse,
    GmailThreadResponse,
    WaitingItemOut,
    WaitingResponse,
)

router = APIRouter(tags=["gmail"])

_NOT_CONNECTED = (
    "Gmail is not connected. GET /integrations/google/connect to authorize "
    "(you must grant Gmail read access — re-consent if you only connected Calendar)."
)


def _serialize(msg: GmailMessage, classification: Classification) -> EmailMessageOut:
    return EmailMessageOut(
        gmail_id=msg.gmail_id,
        thread_id=msg.thread_id,
        from_email=msg.from_email,
        from_name=msg.from_name,
        to_emails=list(msg.to_emails),
        subject=msg.subject,
        snippet=msg.snippet,
        received_at=msg.received_at.isoformat() if msg.received_at else None,
        is_unread=msg.is_unread,
        direction=classification.direction,
        importance=classification.importance,
        urgency=classification.urgency,
        requires_response=classification.requires_response,
        is_promotional=classification.is_promotional,
        is_calendar_related=classification.is_calendar_related,
        is_deadline_related=classification.is_deadline_related,
        is_fyi=classification.is_fyi,
    )


async def _list_response(fetch) -> GmailListResponse:
    try:
        my_email = await gmail.get_profile_email()
        messages = await fetch()
    except gmail.NotConnectedError:
        return GmailListResponse(connected=False, count=0, detail=_NOT_CONNECTED)
    items = [_serialize(m, classify(m, my_email)) for m in messages]
    return GmailListResponse(connected=True, count=len(items), messages=items)


@router.get("/gmail/unread", response_model=GmailListResponse)
async def gmail_unread(_: None = Depends(require_token)) -> GmailListResponse:
    limit = get_settings().gmail_unread_max
    return await _list_response(lambda: gmail.list_unread(max_results=limit))


@router.get("/gmail/today", response_model=GmailListResponse)
async def gmail_today(_: None = Depends(require_token)) -> GmailListResponse:
    limit = get_settings().gmail_unread_max
    return await _list_response(lambda: gmail.list_today(max_results=limit))


@router.get("/gmail/search", response_model=GmailListResponse)
async def gmail_search(
    q: str = Query(min_length=1, max_length=500), _: None = Depends(require_token)
) -> GmailListResponse:
    limit = get_settings().gmail_unread_max
    return await _list_response(lambda: gmail.search(q, max_results=limit))


@router.get("/gmail/thread/{thread_id}", response_model=GmailThreadResponse)
async def gmail_thread(thread_id: str, _: None = Depends(require_token)) -> GmailThreadResponse:
    try:
        my_email = await gmail.get_profile_email()
        messages = await gmail.get_thread(thread_id)
    except gmail.NotConnectedError:
        return GmailThreadResponse(connected=False, thread_id=thread_id, detail=_NOT_CONNECTED)
    items = [_serialize(m, classify(m, my_email)) for m in messages]
    return GmailThreadResponse(connected=True, thread_id=thread_id, messages=items)


def _waiting_out(item: WaitingItem, now: datetime) -> WaitingItemOut:
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


@router.get("/gmail/waiting", response_model=WaitingResponse)
async def gmail_waiting(_: None = Depends(require_token)) -> WaitingResponse:
    try:
        await sync.sync_recent()  # refresh the ledger from Gmail before reporting
    except gmail.NotConnectedError:
        return WaitingResponse(connected=False, detail=_NOT_CONNECTED)
    now = datetime.now(UTC)
    them: list[WaitingItemOut] = []
    me: list[WaitingItemOut] = []
    for item in await waiting.list_waiting():
        (them if item.kind == waiting.WAITING_ON_THEM else me).append(_waiting_out(item, now))
    return WaitingResponse(connected=True, waiting_on_them=them, waiting_on_me=me)
