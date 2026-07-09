"""Memory-inspection endpoints (Phase 2C.5) — the auditable window into what Jarvis believes.

Every conclusion/pattern/commitment is returned with its confidence, evidence breakdown, source
list, and timestamps, so the memory is fully explainable. All read-only w.r.t. external systems;
POST /memory/consolidate (re)builds memory from existing data only — no new external setup.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.db.models import DetectedPattern, DurableConclusion, ExtractedCommitment
from app.deps import require_token
from app.memory import consolidation, store
from app.schemas import (
    CommitmentOut,
    CommitmentsResponse,
    ConclusionOut,
    ConclusionsResponse,
    ConsolidateResponse,
    ContextTagOut,
    PatternOut,
    PatternsResponse,
)

router = APIRouter(prefix="/memory", tags=["memory"])


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _conclusion_out(
    row: DurableConclusion, tags: dict[str, list[tuple[str, float]]]
) -> ConclusionOut:
    return ConclusionOut(
        kind=row.kind,
        subject=row.subject,
        statement=row.statement,
        confidence=row.confidence,
        evidence=row.evidence or {},
        source_list=row.source_list or [],
        contexts=[
            ContextTagOut(name=name, confidence=conf)
            for name, conf in tags.get(row.subject, [])
        ],
        first_seen=_iso(row.first_seen),
        last_updated=_iso(row.last_updated),
    )


def _pattern_out(row: DetectedPattern) -> PatternOut:
    return PatternOut(
        pattern_type=row.pattern_type,
        subject=row.subject,
        description=row.description,
        confidence=row.confidence,
        evidence=row.evidence or {},
        source_list=row.source_list or [],
        first_seen=_iso(row.first_seen),
        last_updated=_iso(row.last_updated),
    )


def _commitment_out(row: ExtractedCommitment) -> CommitmentOut:
    return CommitmentOut(
        direction=row.direction,
        description=row.description,
        counterparty=row.counterparty,
        due_at=_iso(row.due_at),
        confidence=row.confidence,
        evidence=row.evidence or {},
        source_list=row.source_list or [],
        first_seen=_iso(row.first_seen),
        last_updated=_iso(row.last_updated),
    )


async def _conclusions_response(
    kind: str | None, min_confidence: float | None, max_confidence: float | None
) -> ConclusionsResponse:
    await consolidation.ensure_consolidated()
    rows = await store.list_conclusions(
        kind=kind, min_confidence=min_confidence, max_confidence=max_confidence
    )
    tags = await store.all_entity_contexts()
    items = [_conclusion_out(r, tags) for r in rows]
    return ConclusionsResponse(count=len(items), conclusions=items)


@router.get("/conclusions", response_model=ConclusionsResponse)
async def memory_conclusions(
    _: None = Depends(require_token),
    kind: str | None = Query(default=None),
    min_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
    max_confidence: float | None = Query(default=None, ge=0.0, le=1.0),
) -> ConclusionsResponse:
    """All durable conclusions, most-confident first. Filter by kind / confidence band."""
    return await _conclusions_response(kind, min_confidence, max_confidence)


@router.get("/projects", response_model=ConclusionsResponse)
async def memory_projects(_: None = Depends(require_token)) -> ConclusionsResponse:
    """Conclusions Jarvis holds about the projects you're working on."""
    return await _conclusions_response("project", None, None)


@router.get("/people", response_model=ConclusionsResponse)
async def memory_people(_: None = Depends(require_token)) -> ConclusionsResponse:
    """Conclusions Jarvis holds about the people who matter to you."""
    return await _conclusions_response("person", None, None)


@router.get("/patterns", response_model=PatternsResponse)
async def memory_patterns(_: None = Depends(require_token)) -> PatternsResponse:
    """Behavioral patterns Jarvis has noticed (response times, activity windows, recurring contacts)."""
    await consolidation.ensure_consolidated()
    rows = await store.list_patterns()
    items = [_pattern_out(r) for r in rows]
    return PatternsResponse(count=len(items), patterns=items)


@router.get("/commitments", response_model=CommitmentsResponse)
async def memory_commitments(
    _: None = Depends(require_token),
    direction: str | None = Query(default=None),
) -> CommitmentsResponse:
    """Open loops: replies you owe, follow-ups pending, and flagged deadlines."""
    await consolidation.ensure_consolidated()
    rows = await store.list_commitments(direction=direction)
    items = [_commitment_out(r) for r in rows]
    return CommitmentsResponse(count=len(items), commitments=items)


@router.post("/consolidate", response_model=ConsolidateResponse)
async def memory_consolidate(_: None = Depends(require_token)) -> ConsolidateResponse:
    """(Re)build memory from existing data — Gmail mirror, calendar, captures, conversations."""
    result = await consolidation.consolidate()
    return ConsolidateResponse(
        conclusions=result.conclusions,
        patterns=result.patterns,
        commitments=result.commitments,
        context_tags=result.context_tags,
    )
