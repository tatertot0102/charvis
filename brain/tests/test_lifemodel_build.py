"""Life Graph build from a derived MemorySet (Phase 2D.4).

A project and a person that share a real email thread become connected nodes with a grounded
`works_on` edge; commitments and routines attach as evidence-backed facts on the right node.
"""
from datetime import UTC, datetime

import pytest

from app.lifemodel import build, graph
from app.memory.schema import (
    DerivedCommitment,
    DerivedConclusion,
    DerivedPattern,
    Evidence,
    MemorySet,
    SourceRef,
)

pytestmark = pytest.mark.asyncio

ACCOUNT = "test_build"
_WHEN = datetime(2026, 6, 1, 15, 0, tzinfo=UTC)


def _evidence(*refs: SourceRef) -> Evidence:
    ev = Evidence()
    for ref in refs:
        ev.add(ref)
    return ev


def _memory() -> MemorySet:
    shared_thread = SourceRef("gmail", "t1", "email: ARISE onboarding", _WHEN)
    project = DerivedConclusion(
        kind="project", subject="ARISE",
        statement="“ARISE” looks like an active project.", confidence=0.9,
        evidence=_evidence(shared_thread, SourceRef("calendar", "e1", "event: ARISE kickoff", _WHEN)),
        contexts=("Research",),
    )
    person = DerivedConclusion(
        kind="person", subject="luann@stonybrook.edu",
        statement="LuAnn Williams is an important contact.", confidence=0.85,
        evidence=_evidence(shared_thread), display_name="LuAnn Williams",
    )
    commitment = DerivedCommitment(
        dedupe_key="waiting:t1", direction="owed_by_me",
        description="Reply to LuAnn about ARISE onboarding.", confidence=0.7,
        evidence=_evidence(shared_thread), counterparty="luann@stonybrook.edu",
    )
    routine = DerivedPattern(
        pattern_type="routine", subject="ARISE",
        description="“ARISE” happens on most weekdays.", confidence=0.6,
        evidence=_evidence(SourceRef("calendar", "e1", "event: ARISE kickoff", _WHEN)),
    )
    return MemorySet(
        conclusions=(project, person), commitments=(commitment,), patterns=(routine,)
    )


async def test_rebuild_creates_connected_grounded_graph():
    result = await build.rebuild(_memory(), ACCOUNT)
    assert result.projects == 1
    assert result.people == 1
    assert result.edges == 1  # the shared thread ties LuAnn to ARISE

    hood = await graph.neighborhood_for_name(ACCOUNT, "ARISE")
    assert hood is not None
    assert hood["importance"] == 0.9
    assert hood["inferred_role"] == "Research"

    predicates = {f["predicate"] for f in hood["facts"]}
    assert {"summary", "commitment", "routine"} <= predicates

    # the works_on edge is visible and grounded by the one shared record
    edges = [e for e in hood["edges"] if e["relation_type"] == "works_on"]
    assert len(edges) == 1
    assert edges[0]["other_name"] == "LuAnn Williams"
    assert edges[0]["evidence_count"] == 1


async def test_email_alias_resolves_person_node():
    await build.rebuild(_memory(), ACCOUNT)
    # both the name and the email address resolve to the same person node
    by_name = await graph.neighborhood_for_name(ACCOUNT, "LuAnn Williams")
    by_email = await graph.neighborhood_for_name(ACCOUNT, "luann@stonybrook.edu")
    assert by_name is not None and by_email is not None
    assert by_name["id"] == by_email["id"]


async def test_rebuild_is_idempotent_no_duplicate_edges():
    await build.rebuild(_memory(), ACCOUNT)
    await build.rebuild(_memory(), ACCOUNT)
    snap = await graph.graph_snapshot(ACCOUNT)
    works_on = [e for e in snap["edges"] if e["relation_type"] == "works_on"]
    assert len(works_on) == 1
