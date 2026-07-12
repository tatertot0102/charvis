"""The Grounded Reasoning Layer (Phase 2D.4) — reason over evidence, never fabricate.

`narrate(...)` is the single entry point the conversation layer uses. It takes the WorldModel a
handler already built, augments it with the durable Life Graph, asks the LLM to reason over ONLY that
evidence, and truth-gates the result — falling back to the deterministic renderer whenever a real LLM
isn't configured (tests/offline) or the generated prose fails the guard. So callers get natural prose
in production and identical deterministic prose everywhere else, with fabrication structurally blocked.
"""
from __future__ import annotations

from collections.abc import Callable

from app.knowledge.model import WorldModel
from app.reasoning import collect, guard, reason
from app.reasoning.collect import GroundedContext
from app.telemetry import get_logger

log = get_logger(__name__)

Fallback = Callable[[], str]


async def narrate(
    world: WorldModel,
    *,
    kind: str,
    question: str,
    fallback: Fallback,
    account: str = "default",
    label: str | None = None,
) -> str:
    """Compose a grounded natural answer, or return the deterministic `fallback()` if unavailable."""
    if not reason.reasoning_available():
        return fallback()
    try:
        context = await collect.build_context(
            world, question=question, kind=kind, account=account, label=label
        )
        prose = await reason.compose(context)
    except Exception as exc:  # noqa: BLE001 — any reasoning failure degrades to the safe renderer.
        log.error("reasoning_failed", kind=kind, error=str(exc), error_type=type(exc).__name__)
        return fallback()

    safe = guard.validate(prose, context)
    if safe is None:
        log.info("reasoning_rejected_by_guard", kind=kind)
        return fallback()
    return safe


__all__ = ["narrate", "collect", "reason", "guard", "GroundedContext"]
