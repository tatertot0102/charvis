"""People — the contacts slice of the life model (CLAUDE.md §5).

Additive only: every email sync records an interaction, updating last-contact timestamps and a
running count. Rows are never deleted here. Richer life-model facts (projects, deadlines,
commitments) are a later phase — Phase 2B only maintains the deterministic people signal.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Person
from app.db.session import get_session


async def record_interaction(
    session: AsyncSession,
    *,
    account: str,
    email: str,
    name: str | None,
    direction: str,  # inbound | outbound
    at: datetime | None,
) -> None:
    """Upsert a person and fold in one interaction. Operates within the caller's transaction."""
    if not email:
        return
    email = email.lower()
    row = (
        await session.execute(
            select(Person).where(Person.account == account, Person.email == email)
        )
    ).scalar_one_or_none()
    if row is None:
        row = Person(account=account, email=email, name=name, message_count=0)
        session.add(row)
    if name and not row.name:
        row.name = name
    row.message_count = (row.message_count or 0) + 1

    if direction == "inbound":
        if at and (row.last_inbound_at is None or at > row.last_inbound_at):
            row.last_inbound_at = at
    elif at and (row.last_outbound_at is None or at > row.last_outbound_at):
        row.last_outbound_at = at

    if at and (row.last_interaction_at is None or at > row.last_interaction_at):
        row.last_interaction_at = at


async def find_person(name_or_email: str, account: str = "default") -> Person | None:
    """Best-effort lookup by email substring or (case-insensitive) name substring."""
    needle = name_or_email.strip().lower()
    if not needle:
        return None
    async with get_session() as session:
        result = await session.execute(
            select(Person)
            .where(Person.account == account)
            .order_by(Person.last_interaction_at.desc().nullslast())
        )
        people = list(result.scalars().all())
    for person in people:
        if needle in person.email.lower():
            return person
    for person in people:
        if person.name and needle in person.name.lower():
            return person
    return None
