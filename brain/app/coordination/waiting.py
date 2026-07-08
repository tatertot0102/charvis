"""Waiting-on ledger (CLAUDE.md §8) — DETECTION ONLY in Phase 2B.

Splits stalled threads into "waiting on them" (I sent the last message) vs "waiting on me" (they
sent the last message and it needs a reply). Jarvis records and surfaces these; it never sends a
follow-up in this phase. The analysis is pure and unit-testable; persistence is a thin upsert.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import WaitingItem
from app.db.session import get_session
from app.integrations.google.classify import classify, is_noreply
from app.integrations.google.gmail import GmailMessage

DEFAULT_FOLLOWUP_DAYS = 4

WAITING_ON_THEM = "waiting_on_them"
WAITING_ON_ME = "waiting_on_me"


@dataclass(frozen=True)
class WaitingAnalysis:
    kind: str  # waiting_on_them | waiting_on_me
    thread_id: str
    person_email: str | None
    subject: str
    last_message_at: datetime | None
    last_message_direction: str  # inbound | outbound
    follow_up_recommended: bool


def _age_days(then: datetime | None, now: datetime) -> int:
    if then is None:
        return 0
    return max(0, (now - then).days)


def analyze_thread(
    thread: list[GmailMessage],
    my_email: str,
    followup_days: int = DEFAULT_FOLLOWUP_DAYS,
    now: datetime | None = None,
) -> WaitingAnalysis | None:
    """Return a waiting item for this thread, or None if nobody is waiting on anybody."""
    if not thread:
        return None
    now = now or datetime.now(UTC)
    my = (my_email or "").lower()
    last = thread[-1]
    last_direction = "outbound" if my and last.from_email == my else "inbound"
    subject = last.subject or ""

    if last_direction == "outbound":
        recipient = last.to_emails[0] if last.to_emails else None
        if not recipient or is_noreply(recipient):
            return None
        return WaitingAnalysis(
            kind=WAITING_ON_THEM,
            thread_id=last.thread_id,
            person_email=recipient,
            subject=subject,
            last_message_at=last.received_at,
            last_message_direction=last_direction,
            follow_up_recommended=_age_days(last.received_at, now) >= followup_days,
        )

    classification = classify(last, my_email)
    if classification.is_promotional or not classification.requires_response:
        return None
    return WaitingAnalysis(
        kind=WAITING_ON_ME,
        thread_id=last.thread_id,
        person_email=last.from_email,
        subject=subject,
        last_message_at=last.received_at,
        last_message_direction=last_direction,
        follow_up_recommended=False,  # the action here is mine (reply), surfaced separately
    )


async def upsert_waiting_item(
    session: AsyncSession, analysis: WaitingAnalysis, account: str = "default"
) -> None:
    """Upsert one thread's waiting state within the caller's transaction."""
    row = (
        await session.execute(
            select(WaitingItem).where(
                WaitingItem.account == account, WaitingItem.thread_id == analysis.thread_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = WaitingItem(account=account, thread_id=analysis.thread_id)
        session.add(row)
    row.kind = analysis.kind
    row.person_email = analysis.person_email
    row.subject = analysis.subject
    row.last_message_at = analysis.last_message_at
    row.last_message_direction = analysis.last_message_direction
    row.follow_up_recommended = analysis.follow_up_recommended


async def list_waiting(account: str = "default") -> list[WaitingItem]:
    """All waiting items, most recently active first."""
    async with get_session() as session:
        result = await session.execute(
            select(WaitingItem)
            .where(WaitingItem.account == account)
            .order_by(WaitingItem.last_message_at.desc().nullslast())
        )
        return list(result.scalars().all())
