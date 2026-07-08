"""Briefing synthesis (Phase 2C) — turn assembled context into a concise natural-language brief.

This is the ONE place in Phase 2C that calls the LLM (see ContextResolver design note). We hand the
model a compact, already-resolved context block and ask for a short brief — it never touches Gmail
or Calendar itself, so it can't hallucinate sources. If the model is unavailable or errors, we fall
back to a deterministic template so a briefing is ALWAYS returned (reliability over fluency).
"""
from __future__ import annotations

from datetime import UTC, datetime

from app import llm
from app.context.deadlines import Deadline
from app.context.resolver import (
    EventContext,
    latest_related_message,
    unanswered_question,
)
from app.db.models import WaitingItem
from app.integrations.google.classify import classify
from app.llm import ChatMessage
from app.telemetry import get_logger

log = get_logger(__name__)

_BRIEF_SYSTEM = (
    "You are Jarvis, a concise executive assistant. You are given already-gathered context about "
    "an upcoming meeting: the event, related emails, what the user is waiting on, and their own "
    "notes. Write a SHORT briefing (2-4 sentences, no bullet lists, no preamble) that connects the "
    "dots: what the meeting is likely about, the most relevant email, and anything the user still "
    "owes a reply on. Use ONLY the provided context — never invent people, times, or facts. If a "
    "piece of context is missing, simply omit it."
)


def _when(dt: datetime | None) -> str:
    return dt.strftime("%a %-I:%M %p").replace(" 0", " ") if dt else "an unscheduled time"


def _context_block(context: EventContext) -> str:
    """A compact, factual dump of the resolved context — the LLM's only source material."""
    event = context.event
    lines = [f"EVENT: {event.summary} at {_when(event.start)}"]
    if event.location:
        lines.append(f"LOCATION: {event.location}")
    if event.attendees:
        lines.append(f"ATTENDEES: {', '.join(event.attendees)}")
    if event.description:
        lines.append(f"EVENT NOTES: {event.description[:300]}")

    if context.related_emails:
        lines.append("RELATED EMAILS (newest first):")
        for item in context.related_emails:
            msg = item.message
            when = msg.received_at.strftime("%b %-d") if msg.received_at else "recently"
            sender = msg.from_name or msg.from_email
            lines.append(
                f"  - [{when}] from {sender} — \"{(msg.subject or '(no subject)').strip()}\" "
                f"({item.reason}); snippet: {msg.snippet[:160]}"
            )
    if context.waiting_items:
        lines.append("WAITING-ON:")
        for w in context.waiting_items:
            side = "you owe a reply" if w.kind == "waiting_on_me" else "they owe you a reply"
            lines.append(f"  - {w.person_email or 'someone'}: {side} on \"{w.subject or ''}\"")
    if context.captures:
        lines.append("YOUR NOTES:")
        for cap in context.captures:
            lines.append(f"  - {cap.text}")
    return "\n".join(lines)


def deterministic_briefing(context: EventContext) -> str:
    """Template briefing used as the LLM fallback and for tests — no model required."""
    event = context.event
    parts = [f"Your next meeting is “{event.summary}” at {_when(event.start)}."]
    if event.location:
        parts[-1] = parts[-1][:-1] + f" ({event.location})."

    latest = latest_related_message(context)
    if latest is not None:
        when = latest.received_at.strftime("%b %-d") if latest.received_at else "recently"
        sender = latest.from_name or latest.from_email
        subject = (latest.subject or "(no subject)").strip()
        parts.append(f"Likely related: email “{subject}” from {sender} ({when}).")

    owed = unanswered_question(context)
    if owed is not None:
        who = owed.message.from_name or owed.message.from_email
        parts.append(f"⚠ You haven't replied to {who}'s message yet.")
    elif any(w.kind == "waiting_on_me" for w in context.waiting_items):
        parts.append("⚠ Someone on this thread is waiting on your reply.")

    if context.captures:
        note = context.captures[0].text
        parts.append(f"Your note: “{note}”.")

    if not context.has_context:
        parts.append("I couldn't find related emails or notes for it.")
    return " ".join(parts)


async def generate_briefing(context: EventContext) -> str:
    """LLM-synthesized meeting brief, with a deterministic fallback if the model is unavailable."""
    prompt = [
        ChatMessage(role="system", content=_BRIEF_SYSTEM),
        ChatMessage(role="user", content=_context_block(context)),
    ]
    try:
        reply = await llm.generate(prompt, temperature=0.3, max_tokens=220)
        cleaned = (reply or "").strip()
        if cleaned:
            return cleaned
        log.warning("briefing_llm_empty_fallback")
    except Exception as exc:  # noqa: BLE001 — any model failure degrades to the template.
        log.error("briefing_llm_failed", error=str(exc), error_type=type(exc).__name__)
    return deterministic_briefing(context)


# --- deterministic formatters for the data-shaped answers (no LLM needed) -----


def format_deadlines(deadlines: list[Deadline], now: datetime | None = None) -> str:
    now = now or datetime.now(UTC)
    if not deadlines:
        return "Nothing with a deadline in the next couple of weeks. ✅"
    lines = ["Upcoming deadlines:"]
    for d in deadlines:
        marker = "🔴" if d.urgency == "high" else "•"
        if d.when is not None:
            days = max(0, (d.when - now).days)
            horizon = "today" if days == 0 else ("tomorrow" if days == 1 else f"in {days}d")
            lines.append(f"{marker} {d.title} — {horizon} ({d.detail})".rstrip(" ()"))
        else:
            lines.append(f"{marker} {d.title} — {d.detail}")
    return "\n".join(lines)


def format_next_action(
    context: EventContext | None, waiting_items: list[WaitingItem], deadlines: list[Deadline]
) -> str:
    """One prominent recommendation drawn from the highest-priority signal available."""
    # 1) An unanswered question on the next meeting's thread is the most actionable.
    if context is not None:
        owed = unanswered_question(context)
        if owed is not None:
            who = owed.message.from_name or owed.message.from_email
            return f"Reply to {who} about “{(owed.message.subject or '').strip()}” before your next meeting."
    # 2) A high-urgency deadline.
    high = [d for d in deadlines if d.urgency == "high"]
    if high:
        return f"Handle “{high[0].title}” — it's your most urgent deadline ({high[0].detail})".rstrip(" ()") + "."
    # 3) The oldest thing you owe a reply on.
    owe = [w for w in waiting_items if w.kind == "waiting_on_me"]
    if owe:
        return f"Reply to {owe[0].person_email or 'someone'} about “{owe[0].subject or ''}”."
    # 4) A follow-up that's gone quiet.
    nudge = [w for w in waiting_items if w.kind == "waiting_on_them" and w.follow_up_recommended]
    if nudge:
        return f"Follow up with {nudge[0].person_email or 'someone'} — no reply on “{nudge[0].subject or ''}”."
    return "Nothing urgent right now. You're on top of things. ✅"


def format_did_summary_line(context: EventContext) -> str:
    """A one-liner 'what is this meeting about' answer, deterministic (no LLM)."""
    event = context.event
    latest = latest_related_message(context)
    if latest is not None:
        subject = (latest.subject or "").strip()
        cls = classify(latest, context.my_email)
        tail = " You still owe a reply." if cls.requires_response and latest.is_unread else ""
        return f"“{event.summary}” looks related to the “{subject}” email thread.{tail}"
    if event.description:
        return f"“{event.summary}”: {event.description[:200]}"
    return f"“{event.summary}” — I don't have related emails or notes to go on yet."
