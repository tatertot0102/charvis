"""Ranged schedule answers ("what does my month look like") — Phase 2D.3, defect R1.

Now a thin adapter over the Unified Knowledge Engine: a ranged schedule question is answered by
MERGING the real calendar with remembered commitments and likely email invitations (behavior 1), all
reality-labelled, never invented. The engine reads the calendar (paginated, so a month never
truncates) and every other relevant provider; the renderer turns the merged WorldModel into prose.
"""
from __future__ import annotations

from app import knowledge, reasoning
from app.knowledge import render
from app.query.ranges import TimeRange
from app.telemetry import get_logger

log = get_logger(__name__)


async def handle(text: str, time_range: TimeRange, account: str = "default") -> str:
    """Answer a ranged schedule query from the merged WorldModel. Never raises."""
    try:
        world = await knowledge.query(
            intent="schedule",
            date_range=(time_range.start, time_range.end),
            text=text,
            account=account,
        )
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("schedule_range_failed", error=str(exc), error_type=type(exc).__name__)
        return "Sorry — I couldn't reach your calendar just now. Try again in a moment."
    return await reasoning.narrate(
        world, kind="schedule", question=text, account=account, label=time_range.label,
        fallback=lambda: render.explain_schedule(world, time_range.label),
    )
