"""Format memory-introspection answers for chat (Phase 2C.5).

Shared by Telegram and /chat via the conversation service. Every answer surfaces the *evidence*, not
just the verdict (the explainability requirement): confidences and per-source counts travel with each
conclusion. Read-only; never raises — each branch degrades to a friendly line while detail goes to
the logs. Consolidation runs once lazily if memory is still empty so first-time queries work.
"""
from __future__ import annotations

from app.conversation.intents import MemoryIntent
from app.db.models import DurableConclusion
from app.memory import confidence, consolidation, store
from app.telemetry import get_logger

log = get_logger(__name__)

_ERROR = "Sorry — I couldn't pull that together just now. Try again in a moment."
_NOTHING_YET = (
    "I don't know much about you yet — connect Gmail/Calendar and chat with me, then ask again."
)
_LOW_CONF_CUTOFF = 0.5


def _pct(confidence_value: float) -> str:
    return f"{round(confidence_value * 100)}%"


def _evidence_phrase(row: DurableConclusion) -> str:
    by_source = (row.evidence or {}).get("by_source", {})
    return confidence.explain_by_source(by_source)


def _conclusion_line(row: DurableConclusion, prefix: str = "•") -> str:
    return f"{prefix} {row.statement} (confidence {_pct(row.confidence)})"


async def handle(intent: MemoryIntent, subject: str | None = None) -> str:
    """Answer a memory intent. Never raises — returns user-facing text."""
    try:
        await consolidation.ensure_consolidated()
        if intent is MemoryIntent.WHY:
            return await _why(subject)
        if intent is MemoryIntent.PATTERNS:
            return await _patterns()
        if intent is MemoryIntent.PROJECTS:
            return await _projects()
        if intent is MemoryIntent.LOW_CONFIDENCE:
            return await _low_confidence()
        return await _know_about_me()
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error(
            "memory_intent_failed",
            intent=intent.value,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return _ERROR


async def _know_about_me() -> str:
    projects = await store.list_conclusions(kind="project")
    people = await store.list_conclusions(kind="person")
    patterns = await store.list_patterns()
    commitments = await store.list_commitments()
    if not (projects or people or patterns or commitments):
        return _NOTHING_YET

    lines = ["Here's what I've figured out so far:"]
    if projects:
        lines.append("\nProjects:")
        lines += [_conclusion_line(p) for p in projects[:5]]
    if people:
        lines.append("\nPeople who matter:")
        lines += [_conclusion_line(p) for p in people[:5]]
    if patterns:
        lines.append("\nPatterns:")
        lines += [f"• {p.description} (confidence {_pct(p.confidence)})" for p in patterns[:4]]
    if commitments:
        owed = sum(1 for c in commitments if c.direction == "owed_by_me")
        lines.append(f"\nOpen loops: {len(commitments)} tracked ({owed} you owe a reply/task).")
    lines.append("\nAsk “why do you think …” about any of these to see my evidence.")
    return "\n".join(lines)


async def _projects() -> str:
    projects = await store.list_conclusions(kind="project")
    if not projects:
        return "I haven't spotted any clear projects yet — I need more email/calendar history."
    lines = ["Projects I think you're working on:"]
    for p in projects[:8]:
        contexts = await store.contexts_for_entity(p.subject)
        tag = f" [{', '.join(name for name, _ in contexts)}]" if contexts else ""
        lines.append(f"• {p.subject} — {_evidence_phrase(p)} → confidence {_pct(p.confidence)}{tag}")
    return "\n".join(lines)


async def _patterns() -> str:
    patterns = await store.list_patterns()
    if not patterns:
        return "No clear patterns yet — I'll spot them as more of your history builds up."
    lines = ["Patterns I've noticed:"]
    lines += [f"• {p.description} (confidence {_pct(p.confidence)})" for p in patterns[:10]]
    return "\n".join(lines)


async def _low_confidence() -> str:
    rows = await store.list_conclusions(max_confidence=_LOW_CONF_CUTOFF)
    if not rows:
        return "Nothing shaky right now — every conclusion I hold is reasonably well-supported."
    lines = [f"Conclusions I'm less sure about (under {_pct(_LOW_CONF_CUTOFF)}):"]
    for row in rows:
        lines.append(f"• {row.statement} — only {_evidence_phrase(row)} → {_pct(row.confidence)}")
    return "\n".join(lines)


async def _why(subject: str | None) -> str:
    if not subject:
        return "Ask me “why do you think <project or person> is important?” and I'll show my evidence."
    row = await store.find_conclusion(subject)
    if row is None:
        return (
            f"I don't have a confident view on “{subject}” yet. "
            "I only keep conclusions I can back with evidence."
        )
    lines = [
        f"I think {row.statement}",
        f"Confidence: {_pct(row.confidence)}, from {_evidence_phrase(row)}.",
    ]
    sources = row.source_list or []
    if sources:
        lines.append(f"Sources: {', '.join(sources)}.")
    contexts = await store.contexts_for_entity(row.subject)
    if contexts:
        lines.append(f"Contexts: {', '.join(name for name, _ in contexts)}.")
    return "\n".join(lines)
