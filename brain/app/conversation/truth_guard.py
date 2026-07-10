"""Post-filter for free-form LLM replies (Phase 2D.2) — the core anti-hallucination fix.

The generic chat path hands conversation history to the LLM. Even with a hardened system prompt, a
model can still leak two failure modes the user actually hit: placeholder scaffolding ("[insert
existing events]") and *false write claims* ("I've updated your schedule") when nothing was written.

This module is the structural backstop: it runs on the LLM's output in the generic branch — the one
branch where Jarvis has taken NO action — and replaces any such reply with a safe, honest message.
It never touches the deterministic handlers, which say "✓" only after a confirmed, executed write.
"""
from __future__ import annotations

import re

# Placeholder scaffolding a real answer would never contain.
_PLACEHOLDER_MARKERS = (
    "[insert",
    "[your",
    "[existing",
    "[event",
    "[add ",
    "[time",
    "[title",
    "[list",
    "[name",
    "[date",
)

# A claim to have mutated the calendar/schedule. In the generic branch nothing was written, so any
# such claim is false by construction. Matches "I've updated your schedule", "I added the event",
# "I have scheduled a meeting", "I've moved your appointment", etc.
_FALSE_WRITE_RE = re.compile(
    r"\bi(?:['’]?ve|['’]?ll| have| will| already| just)?\s+"
    r"(?:just\s+|already\s+)?"
    r"(?:updated|added|scheduled|created|deleted|removed|moved|cancell?ed|changed|booked|set up|"
    r"put|blocked off|rescheduled)\b"
    r"[^.\n]{0,50}?"
    r"\b(calendar|schedule|event|events|meeting|meetings|appointment|appointments)\b",
    re.IGNORECASE,
)

SAFE_REPLY = (
    "I understand. Just so we're clear — I haven't changed anything on your calendar. "
    "Tell me the exact change you want and I'll draft it for you to CONFIRM."
)


def is_suspect(reply: str) -> bool:
    """True when the reply contains placeholder scaffolding or a false calendar-write claim."""
    lowered = reply.lower()
    if any(marker in lowered for marker in _PLACEHOLDER_MARKERS):
        return True
    return bool(_FALSE_WRITE_RE.search(reply))


def sanitize(reply: str) -> str:
    """Return the reply unchanged, or the safe message if it fabricates events or claims a write."""
    return SAFE_REPLY if is_suspect(reply) else reply
