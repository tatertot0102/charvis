"""The persistent, connected Life Graph (Phase 2D.4).

Turns Jarvis's memory from a bag of disconnected rows into a graph where everything knows what it is
connected to and *why*. Nodes are `KnowledgeEntity` rows (person / project / commitment / place);
edges are `EntityRelation` rows (person —works_on→ project, project —contains→ commitment); each node
carries evidence-backed `KnowledgeFact`s, and each fact carries the concrete `KnowledgeEvidence` it
came from. The 0009 knowledge tables finally get a writer here.

Two audiences use this module:
  - `lifemodel.build` writes the graph inside one consolidation transaction (pass a `session`).
  - the reasoning layer + read-only APIs read it (`neighborhood`, `graph_snapshot`) with their own
    session.

Nothing here reasons or renders — it only stores and retrieves grounded structure. Reasoning happens
one layer up, over what this returns.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    EntityRelation,
    KnowledgeConflict,
    KnowledgeEntity,
    KnowledgeEvidence,
    KnowledgeFact,
)
from app.db.session import get_session
from app.knowledge import entities as entity_resolver
from app.knowledge.model import Reality
from app.telemetry import get_logger

log = get_logger(__name__)

# memory SourceRef.source → (evidence source_type, provider). Keeps provenance honest: a calendar
# event id lands as a real provider_object_id, not a paraphrase.
_EVIDENCE_KIND = {
    "gmail": ("gmail_thread", "gmail"),
    "calendar": ("calendar_event", "google"),
    "capture": ("capture", None),
    "telegram": ("conversation_message", None),
    "waiting": ("waiting_item", "gmail"),
    "people": ("people", None),
    "memory": ("memory_conclusion", None),
}

# a fact's reality → the persisted truth_status vocabulary (models.KnowledgeFact).
_TRUTH_STATUS = {
    Reality.VERIFIED: "provider_confirmed",
    Reality.LIKELY: "multi_source_confirmed",
    Reality.REMEMBERED: "user_confirmed",
    Reality.INFERRED: "inferred",
}


def truth_status_for(reality: Reality) -> str:
    return _TRUTH_STATUS.get(reality, "unverified")


# --- writes (run inside a caller's transaction) ------------------------------


async def upsert_node(
    session: AsyncSession,
    account: str,
    entity_type: str,
    canonical_name: str,
    *,
    importance: float | None = None,
    inferred_role: str | None = None,
    evidence_count: int | None = None,
    mark_reasoned: bool = False,
) -> KnowledgeEntity:
    """Get-or-create the entity node and (optionally) refresh its derived reasoning attributes."""
    node = await entity_resolver.upsert_entity(session, canonical_name, entity_type, account)
    if importance is not None:
        node.importance = round(float(importance), 3)
    if inferred_role is not None:
        node.inferred_role = inferred_role
    if evidence_count is not None:
        node.evidence_count = int(evidence_count)
    if mark_reasoned:
        node.last_reasoned_at = datetime.now(UTC)
    return node


async def link(
    session: AsyncSession,
    account: str,
    src_entity_id: int,
    dst_entity_id: int,
    relation_type: str,
    *,
    confidence: float = 0.0,
    evidence_count: int = 0,
) -> EntityRelation | None:
    """Upsert a typed edge between two nodes. A self-loop is meaningless and silently skipped."""
    if src_entity_id == dst_entity_id:
        return None
    row = (
        await session.execute(
            select(EntityRelation).where(
                EntityRelation.account == account,
                EntityRelation.src_entity_id == src_entity_id,
                EntityRelation.dst_entity_id == dst_entity_id,
                EntityRelation.relation_type == relation_type,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = EntityRelation(
            account=account, src_entity_id=src_entity_id, dst_entity_id=dst_entity_id,
            relation_type=relation_type,
        )
        session.add(row)
    row.confidence = round(float(confidence), 3)
    row.evidence_count = int(evidence_count)
    return row


async def attach_fact(
    session: AsyncSession,
    account: str,
    entity_id: int,
    predicate: str,
    display_value: str,
    *,
    value_type: str = "text",
    confidence: float = 0.0,
    reality: Reality = Reality.INFERRED,
    valid_from: datetime | None = None,
    valid_until: datetime | None = None,
) -> KnowledgeFact:
    """Upsert one evidence-backed claim about an entity (never a bare assertion)."""
    normalized = entity_resolver.normalize(display_value) or display_value.strip().lower()
    row = (
        await session.execute(
            select(KnowledgeFact).where(
                KnowledgeFact.account == account,
                KnowledgeFact.entity_id == entity_id,
                KnowledgeFact.predicate == predicate,
                KnowledgeFact.normalized_value == normalized,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = KnowledgeFact(
            account=account, entity_id=entity_id, predicate=predicate,
            normalized_value=normalized,
        )
        session.add(row)
    row.display_value = display_value
    row.value_type = value_type
    row.confidence = round(float(confidence), 3)
    row.truth_status = truth_status_for(reality)
    row.valid_from = valid_from
    row.valid_until = valid_until
    if reality is Reality.VERIFIED:
        row.last_verified = datetime.now(UTC)
    await session.flush()  # ensure row.id for evidence
    return row


async def attach_evidence(
    session: AsyncSession,
    account: str,
    fact_id: int,
    *,
    source: str,
    ref: str | None,
    label: str,
    observed_at: datetime | None = None,
    weight: float = 1.0,
) -> None:
    """Attach one concrete provenance record to a fact (idempotent on (fact, dedupe_key))."""
    source_type, provider = _EVIDENCE_KIND.get(source, (source, None))
    dedupe_key = f"{source}:{ref or label}"[:320]
    provider_object_id = ref if provider is not None else None
    existing = (
        await session.execute(
            select(KnowledgeEvidence).where(
                KnowledgeEvidence.fact_id == fact_id,
                KnowledgeEvidence.dedupe_key == dedupe_key,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        existing.excerpt = label
        existing.observed_at = observed_at
        existing.evidence_weight = weight
        return
    session.add(
        KnowledgeEvidence(
            account=account, fact_id=fact_id, source_type=source_type,
            source_record_id=str(ref) if ref is not None else None,
            provider=provider, provider_object_id=provider_object_id,
            dedupe_key=dedupe_key, excerpt=label, observed_at=observed_at,
            freshness_at=datetime.now(UTC), evidence_weight=weight,
        )
    )


async def clear_relations(session: AsyncSession, account: str) -> None:
    """Drop the account's edges before a rebuild so a graph pass is authoritative, not additive.

    Nodes/facts/evidence are upserted (they carry first_seen history); edges are cheap and fully
    recomputed each pass, so wiping them avoids stale relations lingering after data changes.
    """
    from sqlalchemy import delete

    await session.execute(delete(EntityRelation).where(EntityRelation.account == account))


# --- reads (own session; used by reasoning + read-only APIs) -----------------


async def _facts_for(session: AsyncSession, account: str, entity_id: int) -> list[dict]:
    facts = (
        await session.execute(
            select(KnowledgeFact)
            .where(KnowledgeFact.account == account, KnowledgeFact.entity_id == entity_id)
            .order_by(KnowledgeFact.confidence.desc())
        )
    ).scalars().all()
    out: list[dict] = []
    for fact in facts:
        evidence = (
            await session.execute(
                select(KnowledgeEvidence).where(KnowledgeEvidence.fact_id == fact.id)
            )
        ).scalars().all()
        out.append(
            {
                "predicate": fact.predicate,
                "value": fact.display_value,
                "truth_status": fact.truth_status,
                "confidence": fact.confidence,
                "evidence_count": len(evidence),
                "evidence": [
                    {
                        "source_type": e.source_type,
                        "provider": e.provider,
                        "provider_object_id": e.provider_object_id,
                        "excerpt": e.excerpt,
                        "observed_at": e.observed_at.isoformat() if e.observed_at else None,
                    }
                    for e in evidence[:12]
                ],
            }
        )
    return out


async def _edges_for(
    session: AsyncSession, account: str, entity_id: int, name_by_id: dict[int, dict]
) -> list[dict]:
    rows = (
        await session.execute(
            select(EntityRelation).where(
                EntityRelation.account == account,
                (EntityRelation.src_entity_id == entity_id)
                | (EntityRelation.dst_entity_id == entity_id),
            )
        )
    ).scalars().all()
    edges: list[dict] = []
    for r in rows:
        outgoing = r.src_entity_id == entity_id
        other_id = r.dst_entity_id if outgoing else r.src_entity_id
        other = name_by_id.get(other_id)
        edges.append(
            {
                "direction": "outgoing" if outgoing else "incoming",
                "relation_type": r.relation_type,
                "other_id": other_id,
                "other_name": other["canonical_name"] if other else None,
                "other_type": other["entity_type"] if other else None,
                "confidence": r.confidence,
                "evidence_count": r.evidence_count,
            }
        )
    return edges


async def _node_index(session: AsyncSession, account: str) -> dict[int, dict]:
    rows = (
        await session.execute(
            select(KnowledgeEntity).where(KnowledgeEntity.account == account)
        )
    ).scalars().all()
    return {
        n.id: {
            "id": n.id,
            "entity_type": n.entity_type,
            "canonical_name": n.canonical_name,
            "inferred_role": n.inferred_role,
            "importance": n.importance,
            "evidence_count": n.evidence_count,
            "last_reasoned_at": n.last_reasoned_at.isoformat() if n.last_reasoned_at else None,
        }
        for n in rows
    }


async def neighborhood(account: str, entity_id: int) -> dict | None:
    """A node plus its edges, facts, evidence, and open conflicts — the reasoner's grounding unit."""
    async with get_session() as session:
        node = await session.get(KnowledgeEntity, entity_id)
        if node is None or node.account != account:
            return None
        index = await _node_index(session, account)
        aliases = await entity_resolver.list_aliases(session, entity_id, account)
        facts = await _facts_for(session, account, entity_id)
        edges = await _edges_for(session, account, entity_id, index)
        conflicts = (
            await session.execute(
                select(KnowledgeConflict).where(
                    KnowledgeConflict.account == account,
                    KnowledgeConflict.entity_id == entity_id,
                    KnowledgeConflict.status == "open",
                )
            )
        ).scalars().all()
        return {
            "id": node.id,
            "entity_type": node.entity_type,
            "canonical_name": node.canonical_name,
            "aliases": aliases,
            "inferred_role": node.inferred_role,
            "importance": node.importance,
            "evidence_count": node.evidence_count,
            "facts": facts,
            "edges": edges,
            "conflicts": [
                {"predicate": c.predicate, "type": c.conflict_type, "explanation": c.explanation}
                for c in conflicts
            ],
        }


async def neighborhood_for_name(account: str, name: str) -> dict | None:
    """Resolve a mention to its canonical node, then return its neighborhood (or None)."""
    ref = await entity_resolver.resolve_name(name, account)
    if ref is None or ref.entity_id is None:
        return None
    return await neighborhood(account, ref.entity_id)


async def graph_snapshot(account: str) -> dict:
    """Every node + edge for an account — what the dashboard renders as the life graph."""
    async with get_session() as session:
        index = await _node_index(session, account)
        edge_rows = (
            await session.execute(
                select(EntityRelation).where(EntityRelation.account == account)
            )
        ).scalars().all()
    edges = [
        {
            "src": e.src_entity_id,
            "dst": e.dst_entity_id,
            "relation_type": e.relation_type,
            "confidence": e.confidence,
            "evidence_count": e.evidence_count,
        }
        for e in edge_rows
    ]
    nodes = sorted(index.values(), key=lambda n: n["importance"], reverse=True)
    return {"nodes": nodes, "edges": edges}
