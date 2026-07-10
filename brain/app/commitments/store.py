"""Persistence for durable commitments (Phase 2D.2). The only module that reads/writes commitments.

Upsert is additive and idempotent: re-stating a commitment bumps last_seen and merges evidence,
never duplicates. Nothing here touches Google — a commitment is life understanding, not a calendar
write, so updating one is always safe and never implies a calendar change.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.db.models import Commitment
from app.db.session import get_session
from app.telemetry import get_logger

log = get_logger(__name__)

_KEY_STRIP = re.compile(r"[^a-z0-9\s]")


def normalize_key(title: str) -> str:
    """Identity for a commitment — lowercased, punctuation-stripped, whitespace-collapsed."""
    return " ".join(_KEY_STRIP.sub(" ", title.lower()).split())


async def upsert(
    *,
    account: str,
    title: str,
    type: str | None = None,
    schedule_summary: str | None = None,
    recurrence: str | None = None,
    contexts: list[str] | None = None,
    confidence: float | None = None,
    evidence_source: str | None = None,
    linked_event_ids: list[str] | None = None,
    linked_email_ids: list[str] | None = None,
) -> Commitment:
    """Insert or update a commitment keyed by the normalized title. Merges, never overwrites blindly."""
    key = normalize_key(title)
    async with get_session() as session:
        row = (
            await session.execute(
                select(Commitment).where(
                    Commitment.account == account, Commitment.key == key
                )
            )
        ).scalar_one_or_none()

        if row is None:
            row = Commitment(
                account=account,
                key=key,
                title=title,
                type=type,
                schedule_summary=schedule_summary,
                recurrence=recurrence,
                contexts=list(contexts or []),
                confidence=confidence if confidence is not None else 0.5,
                evidence={"sources": [], "mentions": 0},
                linked_event_ids=list(linked_event_ids or []),
                linked_email_ids=list(linked_email_ids or []),
            )
            session.add(row)
        else:
            row.title = title  # a correction updates the display casing/name
            if type is not None:
                row.type = type
            if schedule_summary is not None:
                row.schedule_summary = schedule_summary
            if recurrence is not None:
                row.recurrence = recurrence
            if contexts:
                row.contexts = sorted(set(row.contexts or []) | set(contexts))
            if confidence is not None:
                row.confidence = max(row.confidence, confidence)
            if linked_event_ids:
                row.linked_event_ids = sorted(set(row.linked_event_ids or []) | set(linked_event_ids))
            if linked_email_ids:
                row.linked_email_ids = sorted(set(row.linked_email_ids or []) | set(linked_email_ids))

        evidence = dict(row.evidence or {})
        evidence["mentions"] = int(evidence.get("mentions", 0)) + 1
        sources = list(evidence.get("sources", []))
        if evidence_source and evidence_source not in sources:
            sources.append(evidence_source)
        evidence["sources"] = sources
        row.evidence = evidence

        await session.commit()
        await session.refresh(row)

    log.info("commitment_upserted", account=account, key=key, mentions=row.evidence.get("mentions"))
    return row


async def get_by_key(account: str, key: str) -> Commitment | None:
    async with get_session() as session:
        return (
            await session.execute(
                select(Commitment).where(
                    Commitment.account == account, Commitment.key == key
                )
            )
        ).scalar_one_or_none()


async def latest(account: str) -> Commitment | None:
    """The most recently touched commitment — the referent for a follow-up like "it's every…"."""
    async with get_session() as session:
        return (
            await session.execute(
                select(Commitment)
                .where(Commitment.account == account, Commitment.status == "active")
                .order_by(Commitment.last_seen.desc(), Commitment.id.desc())
            )
        ).scalars().first()


async def list_all(account: str) -> list[Commitment]:
    async with get_session() as session:
        return list(
            (
                await session.execute(
                    select(Commitment)
                    .where(Commitment.account == account)
                    .order_by(Commitment.last_seen.desc())
                )
            ).scalars()
        )
