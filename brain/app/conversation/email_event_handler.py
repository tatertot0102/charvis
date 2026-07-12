"""Search email for events/invitations — Phase 2D.3, defect R3, now via the Knowledge Engine.

"Check my email for upcoming events" runs the engine's email_events path: a real Gmail search for
event-shaped messages (invitations, RSVPs, travel/hotel/flight, meetings), optionally scoped to a
person, cross-checked against the calendar so anything already scheduled is flagged rather than
double-counted. It never denies the capability when Gmail is connected, and reports an empty result
honestly rather than inventing events.
"""
from __future__ import annotations

from app import knowledge, reasoning
from app.knowledge import render
from app.telemetry import get_logger

log = get_logger(__name__)

_ERROR = "Sorry — I couldn't search your email just now. Try again in a moment."


async def handle(text: str, person: str | None = None, account: str = "default") -> str:
    """Search email for event-related messages, optionally scoped to a person. Never raises."""
    try:
        world = await knowledge.query(
            intent="email_events", person=person, text=text, account=account
        )
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("email_event_search_failed", error=str(exc), error_type=type(exc).__name__)
        return _ERROR
    return await reasoning.narrate(
        world, kind="email_events", question=text, account=account,
        fallback=lambda: render.explain_email_events(world, person),
    )
