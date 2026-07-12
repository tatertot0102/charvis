"""Chat glue for entity/relationship questions (Phase 2D.3 integration).

"What is ARISE?", "What is LuAnn related to?", "What do you know about my college applications?" —
these merge EVERY provider through the Unified Knowledge Engine and render the reality-labelled
WorldModel. This handler is deliberately tiny: all the intelligence lives in the engine, which is the
whole point of the integration (the conversation layer becomes thin).
"""
from __future__ import annotations

from app import knowledge, reasoning
from app.knowledge import render
from app.telemetry import get_logger

log = get_logger(__name__)


async def handle_entity(subject: str, account: str = "default") -> str:
    """Answer a "what is X / what is X related to" question from the merged WorldModel. Never raises.

    The WorldModel + Life Graph become the grounded evidence; the reasoning layer narrates it (or, when
    no real LLM is configured, falls back to the deterministic renderer). Facts stay provider-sourced.
    """
    try:
        world = await knowledge.query(
            intent="entity", subjects=[subject], text=subject, account=account
        )
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("entity_query_failed", error=str(exc), error_type=type(exc).__name__)
        return "Sorry — I couldn't pull that together just now. Try again in a moment."
    return await reasoning.narrate(
        world, kind="entity", question=subject, account=account,
        fallback=lambda: render.explain_entity(world, subject),
    )
