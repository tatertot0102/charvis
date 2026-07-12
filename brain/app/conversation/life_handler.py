"""Broad life questions ("what should I focus on?", "what do I do every weekday?") — Phase 2D.4.

These aren't about one entity or one calendar range — they're about the shape of the user's life. So
we assemble a broad, unscoped WorldModel (every provider: calendar, commitments, memory, routines,
waiting) and let the reasoning layer weigh priorities and describe routines over that grounded
evidence. Under the echo/test provider it falls back to the deterministic reality-grouped renderer.
Never raises; never invents.
"""
from __future__ import annotations

from app import knowledge, reasoning
from app.knowledge import render
from app.telemetry import get_logger

log = get_logger(__name__)


async def handle(text: str, account: str = "default") -> str:
    """Answer a broad focus/priority/routine question from the whole life model. Never raises."""
    try:
        world = await knowledge.query(intent="entity", subjects=[], text=text, account=account)
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("life_query_failed", error=str(exc), error_type=type(exc).__name__)
        return "Sorry — I couldn't pull that together just now. Try again in a moment."
    return await reasoning.narrate(
        world, kind="entity", question=text, account=account,
        fallback=lambda: render.explain_entity(world, "your life right now"),
    )
