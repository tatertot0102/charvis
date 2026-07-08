"""Gmail sync (Phase 2B) — pull recent threads, classify, update the read-only mirror + life model.

Read-only: this fetches from Gmail and writes only to Jarvis's own tables (email_messages, people,
waiting_items). It never mutates Gmail. Run on demand (from an endpoint or a "check my email"
message); no background scheduler in this phase.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.coordination import waiting
from app.db.models import EmailMessage
from app.db.session import get_session
from app.integrations.google import gmail
from app.integrations.google.classify import Classification, classify
from app.integrations.google.gmail import GmailMessage
from app.lifemodel import people
from app.telemetry import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class SyncResult:
    threads: int
    messages: int
    waiting_items: int


async def sync_recent(account: str = "default") -> SyncResult:
    """Fetch recent threads, classify every message, and update the mirror, people, and ledger."""
    settings = get_settings()
    my_email = await gmail.get_profile_email(account)
    threads = await gmail.list_recent_threads(
        account,
        max_threads=settings.gmail_sync_max_threads,
        window_days=settings.gmail_sync_window_days,
    )

    message_count = 0
    waiting_count = 0
    async with get_session() as session:
        for thread in threads:
            for msg in thread:
                classification = classify(msg, my_email)
                await _upsert_message(session, account, msg, classification)
                await _record_people(session, account, msg, classification)
                message_count += 1

            analysis = waiting.analyze_thread(
                thread, my_email, followup_days=settings.waiting_followup_days
            )
            if analysis is not None:
                await waiting.upsert_waiting_item(session, analysis, account=account)
                waiting_count += 1
        await session.commit()

    log.info(
        "gmail_synced",
        account=account,
        threads=len(threads),
        messages=message_count,
        waiting=waiting_count,
    )
    return SyncResult(threads=len(threads), messages=message_count, waiting_items=waiting_count)


async def _record_people(
    session: AsyncSession, account: str, msg: GmailMessage, classification: Classification
) -> None:
    if classification.direction == "inbound":
        await people.record_interaction(
            session,
            account=account,
            email=msg.from_email,
            name=msg.from_name,
            direction="inbound",
            at=msg.received_at,
        )
    else:
        for recipient in msg.to_emails:
            await people.record_interaction(
                session,
                account=account,
                email=recipient,
                name=None,
                direction="outbound",
                at=msg.received_at,
            )


async def _upsert_message(
    session: AsyncSession, account: str, msg: GmailMessage, classification: Classification
) -> None:
    row = (
        await session.execute(
            select(EmailMessage).where(
                EmailMessage.account == account, EmailMessage.gmail_id == msg.gmail_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = EmailMessage(account=account, gmail_id=msg.gmail_id)
        session.add(row)
    row.thread_id = msg.thread_id
    row.from_email = msg.from_email
    row.from_name = msg.from_name
    row.to_emails = ",".join(msg.to_emails)
    row.subject = msg.subject
    row.snippet = msg.snippet
    row.received_at = msg.received_at
    row.labels = " ".join(msg.labels)
    row.direction = classification.direction
    row.importance = classification.importance
    row.urgency = classification.urgency
    row.requires_response = classification.requires_response
    row.is_promotional = classification.is_promotional
    row.is_calendar_related = classification.is_calendar_related
    row.is_deadline_related = classification.is_deadline_related
    row.is_fyi = classification.is_fyi
