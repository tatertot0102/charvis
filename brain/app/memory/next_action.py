"""Memory-aware next-action hint (Phase 2C.5).

The existing next-action logic reasons live over calendar + waiting + deadlines. This layer lets a
high-confidence *stored* commitment sharpen that recommendation: a reply you owe or a flagged
deadline that consolidation already surfaced, ranked by confidence. Returns None when memory has
nothing confident enough to lead with, so the caller falls back to the live recommendation.
"""
from __future__ import annotations

from app.memory import store
from app.telemetry import get_logger

log = get_logger(__name__)

# Only let memory override the live recommendation when it is genuinely confident.
MIN_LEAD_CONFIDENCE = 0.4
# Prefer the most actionable direction first.
_DIRECTION_RANK = {"owed_by_me": 0, "deadline": 1, "owed_to_me": 2}


async def suggest_from_memory(account: str = "default") -> str | None:
    """The single highest-priority stored commitment as a recommendation, or None."""
    try:
        commitments = await store.list_commitments(account=account)
    except Exception as exc:  # noqa: BLE001 — never let a memory read break next-action.
        log.error("memory_next_action_failed", error=str(exc), error_type=type(exc).__name__)
        return None

    candidates = [c for c in commitments if c.confidence >= MIN_LEAD_CONFIDENCE]
    if not candidates:
        return None
    candidates.sort(key=lambda c: (_DIRECTION_RANK.get(c.direction, 9), -c.confidence))
    return candidates[0].description
