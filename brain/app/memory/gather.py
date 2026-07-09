"""Gather (Phase 2C.5) — assemble raw Signals from existing data. Uses only data Jarvis already has.

Reads Jarvis's own tables (the Gmail mirror, captures, conversation messages, people, waiting-on
ledger) plus a best-effort long-range Calendar scan. No new external setup: if Calendar isn't
connected, that source is simply empty and derivation degrades gracefully. Read-only.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.config import get_settings
from app.db.models import Capture, Conversation, EmailMessage, Message, Person, WaitingItem
from app.db.session import get_session
from app.integrations.google import calendar
from app.memory.signals import (
    CaptureSignal,
    EmailSignal,
    EventSignal,
    PersonSignal,
    Signals,
    TelegramSignal,
    WaitingSignal,
)
from app.telemetry import get_logger

log = get_logger(__name__)


def _split(csv: str) -> tuple[str, ...]:
    return tuple(part for part in (csv or "").split(",") if part)


async def _gather_emails(account: str, since: datetime) -> list[EmailSignal]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(EmailMessage)
                .where(EmailMessage.account == account)
                .order_by(EmailMessage.received_at.desc().nullslast())
                .limit(2000)
            )
        ).scalars().all()
    out: list[EmailSignal] = []
    for row in rows:
        if row.received_at is not None and row.received_at < since:
            continue
        out.append(
            EmailSignal(
                gmail_id=row.gmail_id,
                thread_id=row.thread_id,
                subject=row.subject or "",
                snippet=row.snippet or "",
                from_email=row.from_email or "",
                from_name=row.from_name,
                to_emails=_split(row.to_emails),
                direction=row.direction,
                received_at=row.received_at,
                is_promotional=row.is_promotional,
                requires_response=row.requires_response,
                is_deadline_related=row.is_deadline_related,
            )
        )
    return out


async def _gather_events(account: str) -> list[EventSignal]:
    settings = get_settings()
    try:
        events = await calendar.list_events_window(
            account,
            back_days=settings.memory_calendar_back_days,
            forward_days=settings.memory_calendar_forward_days,
        )
    except calendar.NotConnectedError:
        log.info("memory_calendar_unavailable")
        return []
    except Exception as exc:  # noqa: BLE001 — a calendar hiccup must not abort consolidation.
        log.error("memory_calendar_failed", error=str(exc), error_type=type(exc).__name__)
        return []
    return [
        EventSignal(
            event_id=e.event_id or e.summary,
            summary=e.summary,
            start=e.start,
            location=e.location,
            attendees=e.attendees,
            description=e.description,
        )
        for e in events
    ]


async def _gather_captures(limit: int) -> list[CaptureSignal]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Capture).order_by(Capture.created_at.desc()).limit(limit)
            )
        ).scalars().all()
    return [CaptureSignal(id=r.id, text=r.text or "", created_at=r.created_at) for r in rows]


async def _gather_telegram(limit: int) -> list[TelegramSignal]:
    async with get_session() as session:
        rows = (
            await session.execute(
                select(Message)
                .join(Conversation, Conversation.id == Message.conversation_id)
                .where(Message.role == "user")
                .order_by(Message.id.desc())
                .limit(limit)
            )
        ).scalars().all()
    return [TelegramSignal(id=r.id, text=r.content or "", created_at=r.created_at) for r in rows]


async def _gather_people(account: str) -> list[PersonSignal]:
    async with get_session() as session:
        rows = (
            await session.execute(select(Person).where(Person.account == account))
        ).scalars().all()
    return [
        PersonSignal(
            email=r.email,
            name=r.name,
            message_count=r.message_count or 0,
            last_inbound_at=r.last_inbound_at,
            last_outbound_at=r.last_outbound_at,
            last_interaction_at=r.last_interaction_at,
        )
        for r in rows
    ]


async def _gather_waiting(account: str) -> list[WaitingSignal]:
    async with get_session() as session:
        rows = (
            await session.execute(select(WaitingItem).where(WaitingItem.account == account))
        ).scalars().all()
    return [
        WaitingSignal(
            kind=r.kind,
            thread_id=r.thread_id,
            person_email=r.person_email,
            subject=r.subject or "",
            last_message_at=r.last_message_at,
            follow_up_recommended=r.follow_up_recommended,
        )
        for r in rows
    ]


async def gather(account: str = "default") -> Signals:
    """Collect all raw signals for one consolidation run from existing data."""
    settings = get_settings()
    now = datetime.now(UTC)
    since = now - timedelta(days=settings.memory_email_lookback_days)
    signals = Signals(
        account=account,
        now=now,
        emails=await _gather_emails(account, since),
        events=await _gather_events(account),
        captures=await _gather_captures(settings.memory_capture_limit),
        telegram=await _gather_telegram(settings.memory_telegram_message_limit),
        people=await _gather_people(account),
        waiting=await _gather_waiting(account),
    )
    log.info(
        "memory_gathered",
        account=account,
        emails=len(signals.emails),
        events=len(signals.events),
        captures=len(signals.captures),
        telegram=len(signals.telegram),
        people=len(signals.people),
        waiting=len(signals.waiting),
    )
    return signals
