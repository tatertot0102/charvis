"""Dynamic reconciliation (Phase 2D.4) — new user statements become durable graph facts.

A stated commitment/schedule or a naming correction is folded into the Life Graph as a Remembered,
evidence-backed fact — and it lives independently of the calendar (deleting an event never erases it).
"""
import pytest

from app.lifemodel import graph
from app.reasoning import reconcile

pytestmark = pytest.mark.asyncio

ACCOUNT = "test_reconcile"


async def test_note_commitment_creates_remembered_schedule_fact():
    await reconcile.note_commitment(
        ACCOUNT, "ECE Machine Learning Lab",
        schedule_summary="every weekday 10–2", recurrence="RRULE:FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR",
    )
    hood = await graph.neighborhood_for_name(ACCOUNT, "ECE Machine Learning Lab")
    assert hood is not None
    facts = {f["predicate"]: f for f in hood["facts"]}
    assert "schedule" in facts
    assert facts["schedule"]["truth_status"] == "user_confirmed"  # Remembered
    assert facts["schedule"]["evidence_count"] >= 1
    assert "recurrence" in facts


async def test_note_correction_attaches_user_confirmed_name():
    await reconcile.note_correction(ACCOUNT, "ARISE Program")
    hood = await graph.neighborhood_for_name(ACCOUNT, "ARISE Program")
    assert hood is not None
    assert any(f["predicate"] == "canonical_name" for f in hood["facts"])


async def test_commitment_fact_is_independent_of_calendar():
    # The remembered commitment lives in the graph regardless of any calendar state — a later
    # calendar delete can never remove it (it isn't sourced from the calendar).
    await reconcile.note_commitment(ACCOUNT, "Standalone Commitment", schedule_summary="Fridays")
    hood = await graph.neighborhood_for_name(ACCOUNT, "Standalone Commitment")
    assert hood is not None
    assert hood["facts"]  # survives with no calendar evidence at all


async def test_reconcile_never_raises_on_empty_input():
    await reconcile.note_commitment(ACCOUNT, "")  # no-op, must not raise
    await reconcile.note_correction(ACCOUNT, "   ")
