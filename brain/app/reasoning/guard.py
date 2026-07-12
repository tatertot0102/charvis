"""The truth gate for reasoned prose (Phase 2D.4) — Golden Rule #7's backstop.

The LLM may reason, but it may never invent facts. Compose only shows it grounded evidence; this guard
is the structural check on what it wrote. It rejects prose that:
  - fabricates a clock time or calendar date not present in the evidence (the worst failure — inventing
    "your lab runs 10 AM–2 PM" when nothing says so),
  - invents an email address not in the evidence,
  - affirms something is on the calendar when the verified evidence shows nothing,
  - or trips the existing placeholder / false-write / capability-denial guards (2D.2 / 2D.3).

Rejection is safe by construction: the caller falls back to the deterministic renderer, which only
ever describes what the WorldModel actually holds. So the guard errs toward rejecting the uncertain.
"""
from __future__ import annotations

import re

from app.conversation import truth_guard
from app.knowledge.entities import normalize
from app.query import validate as query_validate
from app.reasoning.collect import GroundedContext

# clock times: "10 am", "10:30am", "2 p.m.", 24h "14:00"
_TIME_RE = re.compile(
    r"\b(?:[01]?\d|2[0-3]):[0-5]\d\b|\b(?:1[0-2]|0?[1-9])(?::[0-5]\d)?\s*[ap]\.?m\.?\b",
    re.IGNORECASE,
)
_MONTHS = (
    "january|february|march|april|may|june|july|august|september|october|november|december|"
    "jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec"
)
# calendar dates: "June 5", "5 June", "6/5"
_DATE_RE = re.compile(
    rf"\b(?:{_MONTHS})\.?\s+\d{{1,2}}\b|\b\d{{1,2}}\s+(?:{_MONTHS})\b|\b\d{{1,2}}/\d{{1,2}}\b",
    re.IGNORECASE,
)
_EMAIL_RE = re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")
_AFFIRM_PRESENCE_RE = re.compile(
    r"\b(?:yes\b|it'?s on|that'?s on|is on your (?:google )?calendar|you have it (?:on|scheduled))",
    re.IGNORECASE,
)
_MONTH_NUM = {
    "january": 1, "jan": 1, "february": 2, "feb": 2, "march": 3, "mar": 3, "april": 4, "apr": 4,
    "may": 5, "june": 6, "jun": 6, "july": 7, "jul": 7, "august": 8, "aug": 8,
    "september": 9, "sep": 9, "sept": 9, "october": 10, "oct": 10, "november": 11, "nov": 11,
    "december": 12, "dec": 12,
}


def _time_key(match: str) -> str:
    """Canonical 12h key so '10 AM', '10:00 AM', and '10:00' all compare equal."""
    m = match.lower().replace(".", "").replace(" ", "")
    if m.endswith("am") or m.endswith("pm"):
        mer, digits = m[-2:], m[:-2]
        hour, _, minute = digits.partition(":")
        return f"{int(hour)}:{int(minute or 0):02d}{mer}"
    hour_s, _, minute_s = m.partition(":")
    hour, minute = int(hour_s), int(minute_s or 0)
    mer = "am" if hour < 12 else "pm"
    return f"{hour % 12 or 12}:{minute:02d}{mer}"


def _date_key(match: str) -> str:
    """Canonical month/day key so 'June 5', 'Jun 5', '5 June', and '6/5' compare equal."""
    m = match.lower().strip().replace(".", "")
    if "/" in m:
        month, _, day = m.partition("/")
        return f"{int(month)}/{int(day)}"
    parts = m.split()
    if len(parts) == 2:
        a, b = parts
        if a in _MONTH_NUM:
            return f"{_MONTH_NUM[a]}/{int(b)}"
        if b in _MONTH_NUM:
            return f"{_MONTH_NUM[b]}/{int(a)}"
    return m


def _all_grounded(prose: str, pattern: re.Pattern, grounding: str, keyfn) -> bool:
    """True if every match of `pattern` in the prose also appears (by key) in the grounding text."""
    grounded_keys = {keyfn(m) for m in pattern.findall(grounding)}
    for raw in pattern.findall(prose):
        if keyfn(raw) not in grounded_keys:
            return False
    return True


def check(prose: str, context: GroundedContext) -> str | None:
    """Return a rejection reason if the prose fabricates, else None (it's safe to send)."""
    if not prose or not prose.strip():
        return "empty"
    if truth_guard.is_suspect(prose):
        return "placeholder-or-false-write"
    if query_validate.falsely_denies(prose, context.world.sources):
        return "false-capability-denial"

    grounding = context.grounding_text()
    prose_norm = normalize(prose)

    if not _all_grounded(prose, _TIME_RE, grounding, _time_key):
        return "ungrounded-time"
    if not _all_grounded(prose, _DATE_RE, grounding, _date_key):
        return "ungrounded-date"
    if not _all_grounded(prose.lower(), _EMAIL_RE, grounding, lambda m: m.lower()):
        return "ungrounded-email"

    # A verification with no matching verified events must not be answered in the affirmative.
    if context.kind == "verify" and not context.world.events:
        if _AFFIRM_PRESENCE_RE.search(prose) or "on your calendar" in prose_norm:
            return "affirms-absent-event"

    return None


def validate(prose: str, context: GroundedContext) -> str | None:
    """Return the prose if it passes the truth gate, else None (caller renders deterministically)."""
    reason = check(prose, context)
    if reason is not None:
        return None
    return prose
