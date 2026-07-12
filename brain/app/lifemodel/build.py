"""Populate the Life Graph from a consolidation run (Phase 2D.4).

The 2C.5 derivation already produces evidence-backed projects, people, commitments, and routines —
each carrying concrete `SourceRef` records. This module turns that flat `MemorySet` into the
*connected* graph: a node per project/person, a `works_on` edge wherever a person and a project share
real source records (emails, events), and evidence-backed facts (a project's headline, its
commitments, its routines) attached to the right node. Grounded throughout — an edge exists only
because the same email/event ties the two entities together, never because the LLM guessed.

Called at the end of `memory.consolidation.consolidate()`, so the graph refreshes whenever memory
does. Rebuild is authoritative: edges are cleared and recomputed; nodes/facts/evidence upsert (they
keep their history).
"""
from __future__ import annotations

from dataclasses import dataclass

from app.db.session import get_session
from app.knowledge import entities as entity_resolver
from app.knowledge.model import Reality
from app.lifemodel import graph
from app.memory.schema import DerivedConclusion, MemorySet, SourceRef
from app.telemetry import get_logger

log = get_logger(__name__)


@dataclass(frozen=True)
class BuildResult:
    projects: int
    people: int
    edges: int
    facts: int


def _ref_keys(conclusion: DerivedConclusion) -> set[tuple[str, str]]:
    """The concrete (source, ref) records behind a conclusion — the currency of a grounded edge."""
    return {
        (r.source, r.ref)
        for r in conclusion.evidence.records
        if r.ref
    }


async def _attach_evidence_records(
    session, account: str, fact_id: int, records: list[SourceRef], limit: int = 25
) -> None:
    for record in records[:limit]:
        await graph.attach_evidence(
            session, account, fact_id, source=record.source, ref=record.ref,
            label=record.label, observed_at=record.when,
        )


async def rebuild(memory: MemorySet, account: str = "default") -> BuildResult:
    """Rebuild the account's life graph from a derived MemorySet. Idempotent."""
    projects = [c for c in memory.conclusions if c.kind == "project"]
    people = [c for c in memory.conclusions if c.kind == "person"]
    fact_count = 0

    node_by_norm: dict[str, int] = {}  # normalized name → node id, for in-transaction resolution

    async with get_session() as session:
        await graph.clear_relations(session, account)

        # --- project nodes + headline fact ---
        project_index: dict[int, set[tuple[str, str]]] = {}
        for proj in projects:
            node = await graph.upsert_node(
                session, account, "project", proj.subject,
                importance=proj.confidence, evidence_count=len(proj.evidence.records),
                inferred_role=(proj.contexts[0] if proj.contexts else None), mark_reasoned=True,
            )
            fact = await graph.attach_fact(
                session, account, node.id, "summary", proj.statement,
                confidence=proj.confidence, reality=Reality.INFERRED,
            )
            await _attach_evidence_records(session, account, fact.id, proj.evidence.records)
            fact_count += 1
            project_index[node.id] = _ref_keys(proj)
            node_by_norm[node.normalized_name] = node.id

        # --- person nodes (name as label, email aliased so "LuAnn" and the address both resolve) ---
        person_index: dict[int, set[tuple[str, str]]] = {}
        for per in people:
            label = per.display_name or per.subject
            node = await graph.upsert_node(
                session, account, "person", label,
                importance=per.confidence, evidence_count=len(per.evidence.records),
                mark_reasoned=True,
            )
            if per.subject and entity_resolver.normalize(per.subject) != node.normalized_name:
                await entity_resolver.add_alias(
                    session, node.id, per.subject, alias_type="email",
                    source_type="derived", confidence=per.confidence, account=account,
                )
            fact = await graph.attach_fact(
                session, account, node.id, "role", per.statement,
                confidence=per.confidence, reality=Reality.INFERRED,
            )
            await _attach_evidence_records(session, account, fact.id, per.evidence.records)
            fact_count += 1
            person_index[node.id] = _ref_keys(per)
            node_by_norm[node.normalized_name] = node.id

        # --- edges: a person works_on a project when they share concrete source records ---
        edge_count = 0
        for person_id, prefs in person_index.items():
            for project_id, xrefs in project_index.items():
                shared = len(prefs & xrefs)
                if shared == 0:
                    continue
                await graph.link(
                    session, account, person_id, project_id, "works_on",
                    confidence=min(0.95, 0.45 + 0.12 * shared), evidence_count=shared,
                )
                edge_count += 1

        # --- commitments attach as facts on the project they share evidence with ---
        for commitment in memory.commitments:
            crefs = {(r.source, r.ref) for r in commitment.evidence.records if r.ref}
            best_id = _best_overlap(crefs, project_index)
            if best_id is None:
                continue
            fact = await graph.attach_fact(
                session, account, best_id, "commitment", commitment.description,
                confidence=commitment.confidence, reality=Reality.REMEMBERED,
            )
            await _attach_evidence_records(session, account, fact.id, commitment.evidence.records)
            fact_count += 1

        # --- routines attach to the entity whose title matches (resolved in-transaction) ---
        for pattern in memory.patterns:
            if pattern.pattern_type != "routine":
                continue
            entity_id = node_by_norm.get(entity_resolver.normalize(pattern.subject))
            if entity_id is None:
                continue
            fact = await graph.attach_fact(
                session, account, entity_id, "routine", pattern.description,
                confidence=pattern.confidence, reality=Reality.INFERRED,
            )
            await _attach_evidence_records(session, account, fact.id, pattern.evidence.records)
            fact_count += 1

        await session.commit()

    result = BuildResult(
        projects=len(projects), people=len(people), edges=edge_count, facts=fact_count
    )
    log.info(
        "lifegraph_rebuilt", account=account, projects=result.projects,
        people=result.people, edges=result.edges, facts=result.facts,
    )
    return result


def _best_overlap(
    refs: set[tuple[str, str]], index: dict[int, set[tuple[str, str]]]
) -> int | None:
    best_id, best_shared = None, 0
    for entity_id, xrefs in index.items():
        shared = len(refs & xrefs)
        if shared > best_shared:
            best_id, best_shared = entity_id, shared
    return best_id
