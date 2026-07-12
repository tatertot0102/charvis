"""Dynamic reconciliation (Phase 2D.4) — fold new information into the Life Graph as it arrives.

When the user tells Jarvis something durable — "it is ECE Machine Learning Lab", "it's every weekday
10–2" — the existing handlers already update commitment memory and the permanent alias store. This
module makes that knowledge *graph-native*: it attaches a user-confirmed, evidence-backed fact to the
entity node so the reasoning layer and the dashboard see it immediately, without waiting for the next
consolidation pass. Grounded: the evidence is the user's own statement, labelled Remembered.

Merging/splitting of entities is handled by the alias system (`entities.record_correction`); conflict
surfacing (a remembered routine the calendar can't confirm) is handled at query time by the engine.
This module's job is to keep the durable graph in step with what the user just said.
"""
from __future__ import annotations

from app.db.session import get_session
from app.knowledge.model import Reality
from app.lifemodel import graph
from app.telemetry import get_logger

log = get_logger(__name__)


async def note_commitment(
    account: str,
    title: str,
    *,
    schedule_summary: str | None = None,
    recurrence: str | None = None,
    confidence: float = 0.75,
) -> None:
    """Record a user-stated commitment/schedule as a durable, evidence-backed graph fact. Never raises."""
    if not title or not title.strip():
        return
    try:
        async with get_session() as session:
            node = await graph.upsert_node(
                session, account, "commitment", title,
                importance=confidence, mark_reasoned=True,
            )
            display = schedule_summary or "you mentioned this commitment"
            predicate = "schedule" if (schedule_summary or recurrence) else "note"
            fact = await graph.attach_fact(
                session, account, node.id, predicate, display,
                confidence=confidence, reality=Reality.REMEMBERED,
            )
            await graph.attach_evidence(
                session, account, fact.id, source="telegram", ref=None,
                label=f"you told me: {title} — {display}",
            )
            if recurrence:
                await graph.attach_fact(
                    session, account, node.id, "recurrence", recurrence,
                    confidence=confidence, reality=Reality.REMEMBERED,
                )
            await session.commit()
        log.info("reconciled_commitment", account=account, title=title)
    except Exception as exc:  # noqa: BLE001 — reconciliation is best-effort; never break the reply.
        log.warning("reconcile_commitment_failed", error=str(exc), error_type=type(exc).__name__)


async def note_correction(account: str, canonical_name: str) -> None:
    """Record a naming correction as a user-confirmed graph fact on the (already-aliased) entity.

    `entities.record_correction` has, by this point, created/canonicalized the node and aliased the old
    name to it forever. Here we simply attach the durable "this is what it's called" fact so the graph
    reflects the correction as evidence, not just as an alias. Never raises.
    """
    if not canonical_name or not canonical_name.strip():
        return
    try:
        async with get_session() as session:
            node = await graph.upsert_node(
                session, account, "commitment", canonical_name, mark_reasoned=True
            )
            fact = await graph.attach_fact(
                session, account, node.id, "canonical_name", canonical_name,
                confidence=0.9, reality=Reality.REMEMBERED,
            )
            await graph.attach_evidence(
                session, account, fact.id, source="telegram", ref=None,
                label=f"you corrected the name to: {canonical_name}",
            )
            await session.commit()
        log.info("reconciled_correction", account=account, name=canonical_name)
    except Exception as exc:  # noqa: BLE001
        log.warning("reconcile_correction_failed", error=str(exc), error_type=type(exc).__name__)
