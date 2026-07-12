"""Calendar verification ("is X on my Google Calendar?") — Phase 2D.3, defect R4, via the engine.

The user asks whether something is really on their calendar; the Knowledge Engine reads the provider
(verify intent → CalendarProvider only) and returns matching VERIFIED events. The renderer gives a
truthful yes with the real event or a truthful no that never invents one, and never denies the
capability when the calendar is connected. A missing match is "not found", not proof of absence.
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from app import knowledge, reasoning
from app.config import get_settings
from app.knowledge import render
from app.telemetry import get_logger

log = get_logger(__name__)

_NO_SUBJECT = "What would you like me to check is on your calendar?"
_ERROR = "Sorry — I couldn't check your calendar just now. Try again in a moment."


async def handle(subject: str | None, account: str = "default") -> str:
    """Answer "is <subject> on my calendar?" from the engine's verified events. Never raises."""
    if not subject or not subject.strip():
        return _NO_SUBJECT
    settings = get_settings()
    now = datetime.now(UTC)
    window = (
        now - timedelta(days=settings.calendar_action_lookback_days),
        now + timedelta(days=settings.calendar_action_lookahead_days),
    )
    try:
        world = await knowledge.query(
            intent="verify", subjects=[subject], date_range=window, text=subject, account=account
        )
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("verify_failed", error=str(exc), error_type=type(exc).__name__)
        return _ERROR
    return await reasoning.narrate(
        world, kind="verify", question=subject, account=account,
        fallback=lambda: render.explain_verify(world, subject),
    )
