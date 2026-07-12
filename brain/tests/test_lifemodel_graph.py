"""Life Graph persistence primitives (Phase 2D.4).

Nodes upsert, edges link, facts carry evidence, and neighborhood/snapshot read it all back —
grounded, connected, and de-duplicated on rebuild.
"""
import pytest

from app.db.session import get_session
from app.knowledge.model import Reality
from app.lifemodel import graph

pytestmark = pytest.mark.asyncio

ACCOUNT = "test_graph"


async def _seed() -> tuple[int, int]:
    async with get_session() as session:
        person = await graph.upsert_node(
            session, ACCOUNT, "person", "LuAnn Williams", importance=0.9, evidence_count=7,
            inferred_role="ARISE coordinator", mark_reasoned=True,
        )
        project = await graph.upsert_node(
            session, ACCOUNT, "project", "ARISE", importance=0.95, evidence_count=18,
        )
        await session.flush()
        fact = await graph.attach_fact(
            session, ACCOUNT, project.id, "purpose",
            "ARISE is an active summer research program", confidence=0.9, reality=Reality.INFERRED,
        )
        await graph.attach_evidence(
            session, ACCOUNT, fact.id, source="calendar", ref="evt123",
            label="event: ARISE kickoff",
        )
        await graph.attach_evidence(  # idempotent second call, same dedupe_key
            session, ACCOUNT, fact.id, source="calendar", ref="evt123",
            label="event: ARISE kickoff",
        )
        await graph.link(
            session, ACCOUNT, person.id, project.id, "works_on",
            confidence=0.8, evidence_count=5,
        )
        await session.commit()
        return person.id, project.id


async def test_upsert_is_idempotent():
    async with get_session() as session:
        a = await graph.upsert_node(session, ACCOUNT, "project", "ARISE")
        await session.commit()
    async with get_session() as session:
        b = await graph.upsert_node(session, ACCOUNT, "project", "arise")  # normalized match
        await session.commit()
    assert a.id == b.id


async def test_neighborhood_returns_connected_grounded_node():
    person_id, project_id = await _seed()

    hood = await graph.neighborhood(ACCOUNT, project_id)
    assert hood is not None
    assert hood["canonical_name"] == "ARISE"
    assert hood["importance"] == 0.95

    # the fact is present with exactly one evidence record (the second attach was idempotent)
    assert len(hood["facts"]) == 1
    fact = hood["facts"][0]
    assert fact["predicate"] == "purpose"
    assert fact["truth_status"] == "inferred"
    assert fact["evidence_count"] == 1
    assert fact["evidence"][0]["provider_object_id"] == "evt123"

    # the edge back to the person is visible from the project side
    assert len(hood["edges"]) == 1
    edge = hood["edges"][0]
    assert edge["relation_type"] == "works_on"
    assert edge["other_id"] == person_id
    assert edge["other_name"] == "LuAnn Williams"


async def test_link_is_directional_and_idempotent():
    person_id, project_id = await _seed()
    async with get_session() as session:
        await graph.link(
            session, ACCOUNT, person_id, project_id, "works_on",
            confidence=0.85, evidence_count=6,
        )
        await session.commit()
    snap = await graph.graph_snapshot(ACCOUNT)
    works_on = [e for e in snap["edges"] if e["relation_type"] == "works_on"]
    assert len(works_on) == 1  # upserted, not duplicated
    assert works_on[0]["confidence"] == 0.85


async def test_self_loop_is_skipped():
    async with get_session() as session:
        node = await graph.upsert_node(session, ACCOUNT, "project", "Solo")
        await session.flush()
        result = await graph.link(session, ACCOUNT, node.id, node.id, "works_on")
        await session.commit()
    assert result is None


async def test_neighborhood_by_name_resolves_aliases():
    _, project_id = await _seed()
    hood = await graph.neighborhood_for_name(ACCOUNT, "ARISE")
    assert hood is not None
    assert hood["id"] == project_id
