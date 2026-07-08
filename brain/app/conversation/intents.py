"""Lightweight, deterministic intent detection used before falling back to the LLM.

Phase 2A only needs one intent: "what's my day?" → answer from the calendar, not the model. Kept as
plain string matching (no LLM) so it's fast, free, and reliable. Broader NL intent parsing is a
later-phase concern.
"""
import re

_STRIP_PUNCT = re.compile(r"[^a-z0-9\s]")

# Apostrophe-free phrases (normalization strips punctuation, so "what's" → "whats").
_SCHEDULE_PHRASES: tuple[str, ...] = (
    "whats my day",
    "what is my day",
    "hows my day",
    "how does my day look",
    "what does my day look like",
    "whats on my calendar",
    "whats on the calendar",
    "whats on my schedule",
    "whats my schedule",
    "my schedule today",
    "todays schedule",
    "schedule for today",
    "what do i have today",
    "what am i doing today",
    "whats on today",
    "whats happening today",
    "whats my agenda",
    "todays agenda",
    "agenda today",
)


def _normalize(text: str) -> str:
    return " ".join(_STRIP_PUNCT.sub("", text.lower()).split())


def is_todays_schedule_query(text: str) -> bool:
    """True when the message is asking about today's calendar/schedule."""
    normalized = _normalize(text)
    return any(phrase in normalized for phrase in _SCHEDULE_PHRASES)
