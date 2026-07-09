"""Persistence + reads for the memory tables (Phase 2C.5).

Upserts are idempotent: re-running consolidation updates a conclusion's confidence/evidence in
place (preserving first_seen) rather than duplicating it. Reads expose confidence, evidence, source
list, and timestamps so the memory is fully auditable by the API and Telegram introspection.
Read-only w.r.t. external systems — this only writes Jarvis's own tables.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select, tuple_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    Context,
    DetectedPattern,
    DurableConclusion,
    EntityContext,
    ExtractedCommitment,
)
from app.db.session import get_session
from app.memory import contexts as ctx_defs
from app.memory.schema import (
    DerivedCommitment,
    DerivedConclusion,
    DerivedPattern,
    MemorySet,
)
from app.telemetry import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class PersistResult:
    conclusions: int
    patterns: int
    commitments: int
    context_tags: int


# --- persistence -------------------------------------------------------------


async def _seed_contexts(session: AsyncSession, account: str) -> dict[str, int]:
    """Ensure the canonical contexts exist; return {name: id} for tagging."""
    existing = {
        row.name: row.id
        for row in (
            await session.execute(select(Context).where(Context.account == account))
        ).scalars()
    }
    for name, description in ctx_defs.CANONICAL_CONTEXTS.items():
        if name not in existing:
            row = Context(account=account, name=name, description=description)
            session.add(row)
            await session.flush()
            existing[name] = row.id
    return existing


async def _upsert_conclusion(
    session: AsyncSession, account: str, item: DerivedConclusion
) -> None:
    row = (
        await session.execute(
            select(DurableConclusion).where(
                DurableConclusion.account == account,
                DurableConclusion.kind == item.kind,
                DurableConclusion.subject == item.subject,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DurableConclusion(account=account, kind=item.kind, subject=item.subject)
        session.add(row)
    row.statement = item.statement
    row.confidence = item.confidence
    row.evidence = item.evidence.as_dict()
    row.source_list = item.evidence.source_list


async def _upsert_pattern(session: AsyncSession, account: str, item: DerivedPattern) -> None:
    row = (
        await session.execute(
            select(DetectedPattern).where(
                DetectedPattern.account == account,
                DetectedPattern.pattern_type == item.pattern_type,
                DetectedPattern.subject == item.subject,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = DetectedPattern(
            account=account, pattern_type=item.pattern_type, subject=item.subject
        )
        session.add(row)
    row.description = item.description
    row.confidence = item.confidence
    row.evidence = item.evidence.as_dict()
    row.source_list = item.evidence.source_list


async def _upsert_commitment(
    session: AsyncSession, account: str, item: DerivedCommitment
) -> None:
    row = (
        await session.execute(
            select(ExtractedCommitment).where(
                ExtractedCommitment.account == account,
                ExtractedCommitment.dedupe_key == item.dedupe_key,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ExtractedCommitment(account=account, dedupe_key=item.dedupe_key)
        session.add(row)
    row.direction = item.direction
    row.description = item.description
    row.counterparty = item.counterparty
    row.due_at = item.due_at
    row.confidence = item.confidence
    row.evidence = item.evidence.as_dict()
    row.source_list = item.evidence.source_list


async def _upsert_entity_context(
    session: AsyncSession, account: str, entity_type: str, entity_key: str,
    context_id: int, confidence: float,
) -> None:
    row = (
        await session.execute(
            select(EntityContext).where(
                EntityContext.account == account,
                EntityContext.entity_type == entity_type,
                EntityContext.entity_key == entity_key,
                EntityContext.context_id == context_id,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = EntityContext(
            account=account, entity_type=entity_type, entity_key=entity_key,
            context_id=context_id,
        )
        session.add(row)
    row.confidence = confidence


async def _prune(session: AsyncSession, account: str, memory: MemorySet) -> None:
    """Delete rows no longer supported by the current derivation, so memory stays authoritative.

    Per-category guard: a category is only pruned when this run produced at least one item for it,
    so a transient empty gather (e.g. the mirror briefly unavailable) never wipes good memory.
    """
    kept_conclusions = [(c.kind, c.subject) for c in memory.conclusions]
    if kept_conclusions:
        subjects = [subject for _, subject in kept_conclusions]
        await session.execute(
            delete(DurableConclusion).where(
                DurableConclusion.account == account,
                tuple_(DurableConclusion.kind, DurableConclusion.subject).notin_(kept_conclusions),
            )
        )
        await session.execute(
            delete(EntityContext).where(
                EntityContext.account == account,
                EntityContext.entity_key.notin_(subjects),
            )
        )

    kept_patterns = [(p.pattern_type, p.subject) for p in memory.patterns]
    if kept_patterns:
        await session.execute(
            delete(DetectedPattern).where(
                DetectedPattern.account == account,
                tuple_(DetectedPattern.pattern_type, DetectedPattern.subject).notin_(kept_patterns),
            )
        )

    kept_commitments = [c.dedupe_key for c in memory.commitments]
    if kept_commitments:
        await session.execute(
            delete(ExtractedCommitment).where(
                ExtractedCommitment.account == account,
                ExtractedCommitment.dedupe_key.notin_(kept_commitments),
            )
        )


async def persist(memory: MemorySet, account: str = "default") -> PersistResult:
    """Write a full derived MemorySet, seeding contexts and tagging entities. Idempotent.

    Authoritative: after upserting the fresh derivation it prunes rows no longer supported, so
    re-running never leaves stale conclusions behind (see _prune for the transient-empty guard).
    """
    tag_count = 0
    async with get_session() as session:
        context_ids = await _seed_contexts(session, account)
        for conclusion in memory.conclusions:
            await _upsert_conclusion(session, account, conclusion)
            entity_type = "project" if conclusion.kind == "project" else "person"
            for name in conclusion.contexts:
                cid = context_ids.get(name)
                if cid is None:
                    continue
                await _upsert_entity_context(
                    session, account, entity_type, conclusion.subject, cid, conclusion.confidence
                )
                tag_count += 1
        for pattern in memory.patterns:
            await _upsert_pattern(session, account, pattern)
        for commitment in memory.commitments:
            await _upsert_commitment(session, account, commitment)
        await session.flush()  # ensure this run's rows exist before pruning the rest
        await _prune(session, account, memory)
        await session.commit()

    result = PersistResult(
        conclusions=len(memory.conclusions),
        patterns=len(memory.patterns),
        commitments=len(memory.commitments),
        context_tags=tag_count,
    )
    log.info(
        "memory_persisted",
        account=account,
        conclusions=result.conclusions,
        patterns=result.patterns,
        commitments=result.commitments,
        context_tags=result.context_tags,
    )
    return result


# --- reads -------------------------------------------------------------------


async def has_any_conclusions(account: str = "default") -> bool:
    async with get_session() as session:
        row = (
            await session.execute(
                select(DurableConclusion.id).where(DurableConclusion.account == account).limit(1)
            )
        ).first()
    return row is not None


async def list_conclusions(
    account: str = "default", kind: str | None = None, min_confidence: float | None = None,
    max_confidence: float | None = None,
) -> list[DurableConclusion]:
    async with get_session() as session:
        stmt = select(DurableConclusion).where(DurableConclusion.account == account)
        if kind is not None:
            stmt = stmt.where(DurableConclusion.kind == kind)
        if min_confidence is not None:
            stmt = stmt.where(DurableConclusion.confidence >= min_confidence)
        if max_confidence is not None:
            stmt = stmt.where(DurableConclusion.confidence < max_confidence)
        stmt = stmt.order_by(DurableConclusion.confidence.desc())
        return list((await session.execute(stmt)).scalars().all())


async def list_patterns(account: str = "default") -> list[DetectedPattern]:
    async with get_session() as session:
        stmt = (
            select(DetectedPattern)
            .where(DetectedPattern.account == account)
            .order_by(DetectedPattern.confidence.desc())
        )
        return list((await session.execute(stmt)).scalars().all())


async def list_commitments(
    account: str = "default", direction: str | None = None
) -> list[ExtractedCommitment]:
    async with get_session() as session:
        stmt = select(ExtractedCommitment).where(ExtractedCommitment.account == account)
        if direction is not None:
            stmt = stmt.where(ExtractedCommitment.direction == direction)
        stmt = stmt.order_by(ExtractedCommitment.confidence.desc())
        return list((await session.execute(stmt)).scalars().all())


async def find_conclusion(subject: str, account: str = "default") -> DurableConclusion | None:
    """Best-effort lookup for 'why do you think X …' — exact, then case-insensitive substring."""
    needle = subject.strip().lower()
    if not needle:
        return None
    for conclusion in await list_conclusions(account=account):
        if conclusion.subject.lower() == needle:
            return conclusion
    for conclusion in await list_conclusions(account=account):
        if needle in conclusion.subject.lower() or needle in conclusion.statement.lower():
            return conclusion
    return None


async def contexts_for_entity(
    entity_key: str, account: str = "default"
) -> list[tuple[str, float]]:
    """Return [(context_name, confidence)] an entity is tagged into (overlapping)."""
    async with get_session() as session:
        stmt = (
            select(Context.name, EntityContext.confidence)
            .join(EntityContext, EntityContext.context_id == Context.id)
            .where(EntityContext.account == account, EntityContext.entity_key == entity_key)
            .order_by(EntityContext.confidence.desc())
        )
        return [(name, conf) for name, conf in (await session.execute(stmt)).all()]


async def all_entity_contexts(account: str = "default") -> dict[str, list[tuple[str, float]]]:
    """Every entity→context tag for an account, keyed by entity_key (one query, no N+1)."""
    async with get_session() as session:
        stmt = (
            select(EntityContext.entity_key, Context.name, EntityContext.confidence)
            .join(Context, EntityContext.context_id == Context.id)
            .where(EntityContext.account == account)
            .order_by(EntityContext.confidence.desc())
        )
        rows = (await session.execute(stmt)).all()
    out: dict[str, list[tuple[str, float]]] = {}
    for entity_key, name, conf in rows:
        out.setdefault(entity_key, []).append((name, conf))
    return out
