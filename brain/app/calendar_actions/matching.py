"""Confidence-scored event matching (Phase 2D.1) — pure, deterministic, unit-testable.

Given a request's hints and ONE provider-backed CalendarEvent, produce a confidence in [0,1] and the
human-readable evidence that earned it. No fabrication: every reason cites a real field of the event
(title, attendees, location, description, recurrence). The scoring is the max of the strongest signal
plus small corroboration boosts, so it stays interpretable and bounded.

Signals: exact title-token, acronym-initials, fuzzy title-token, attendee, location, description,
time-of-day. Callers turn these scores into SINGLE / AMBIGUOUS / BULK / NONE decisions (resolve.py).
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from difflib import SequenceMatcher

from app.calendar_actions.schema import ParsedRequest

_WORD = re.compile(r"[a-z0-9]{2,}")
_FUZZY_RATIO = 0.84  # token-level similarity to count as a fuzzy match (e.g. physics↔physic)

# Signal weights → base confidence. Max wins; corroboration adds a small boost.
_W_TITLE_ALL = 0.9  # every keyword present in the title
_W_ATTENDEE = 0.9
_W_ACRONYM = 0.85
_W_TITLE_MOST = 0.6  # ≥ half the keywords present
_W_LOCATION = 0.7
_W_DESCRIPTION = 0.6
_W_TITLE_SOME = 0.4  # at least one keyword present
_W_TIME_ONLY = 0.7  # "my 3pm" with no other hint — the start time identifies the event
_BOOST = 0.05


@dataclass(frozen=True)
class Query:
    """Normalized matching hints derived from a ParsedRequest (pure)."""

    keywords: tuple[str, ...] = ()
    attendee_hint: str | None = None
    target_hour: int | None = None
    target_minute: int | None = None


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def build_query(request: ParsedRequest) -> Query:
    kws = tuple(_WORD.findall((request.target_hint or "").lower())) if request.target_hint else ()
    return Query(
        keywords=kws,
        attendee_hint=(request.attendee_hint or "").lower().strip() or None,
        target_hour=request.target_time.hour if request.target_time else None,
        target_minute=(request.target_time.minute if request.target_time else None),
    )


def _acronym_initials(summary: str) -> str:
    return "".join(w[0] for w in _WORD.findall(summary.lower()))


def _fuzzy_token(kw: str, title_tokens: set[str]) -> bool:
    return any(SequenceMatcher(None, kw, t).ratio() >= _FUZZY_RATIO for t in title_tokens)


def _attendee_matches(hint: str, event) -> bool:
    for addr in getattr(event, "attendees", ()) or ():
        local = addr.split("@", 1)[0]
        if hint == addr or hint in local or hint == local:
            return True
    return False


def _title_signal(keywords: tuple[str, ...], event) -> tuple[float, list[str]]:
    title_tokens = _tokens(event.summary)
    initials = _acronym_initials(event.summary)
    reasons: list[str] = []
    matched = 0
    acronym_hit = False
    for kw in keywords:
        if kw in title_tokens:
            matched += 1
            reasons.append(f"title contains “{kw}”")
        elif _fuzzy_token(kw, title_tokens):
            matched += 1
            reasons.append(f"title ~ “{kw}”")
        elif len(kw) >= 2 and kw in initials:
            matched += 1
            acronym_hit = True
            reasons.append(f"title initials match “{kw.upper()}”")
    if not matched:
        return 0.0, []
    frac = matched / len(keywords)
    if frac >= 1.0:
        base = _W_ACRONYM if acronym_hit and matched == 1 and len(keywords) == 1 else _W_TITLE_ALL
        base = max(base, _W_ACRONYM if acronym_hit else base)
    elif frac >= 0.5:
        base = _W_TITLE_MOST
    else:
        base = _W_TITLE_SOME
    return base, reasons


def score_event(query: Query, event) -> tuple[float, tuple[str, ...]]:
    """Confidence + evidence for one event. 0.0 means no signal fired (never fabricates)."""
    reasons: list[str] = []
    base = 0.0
    corroboration = 0

    title_base, title_reasons = _title_signal(query.keywords, event)
    if title_base:
        base = max(base, title_base)
        reasons += title_reasons
        corroboration += 1

    if query.attendee_hint and _attendee_matches(query.attendee_hint, event):
        base = max(base, _W_ATTENDEE)
        reasons.append(f"attendee matches “{query.attendee_hint}”")
        corroboration += 1

    if query.keywords:
        loc_tokens = _tokens(getattr(event, "location", "") or "")
        if any(kw in loc_tokens for kw in query.keywords):
            base = max(base, _W_LOCATION)
            reasons.append("location matches")
            corroboration += 1
        desc_tokens = _tokens(getattr(event, "description", "") or "")
        if any(kw in desc_tokens for kw in query.keywords):
            base = max(base, _W_DESCRIPTION)
            reasons.append("description mentions it")
            corroboration += 1

    time_hit = False
    if query.target_hour is not None:
        start = getattr(event, "start", None)
        if start is not None and start.hour == query.target_hour and (
            query.target_minute in (None, 0) or start.minute == query.target_minute
        ):
            time_hit = True

    if base == 0.0:
        # A start time can identify an event on its own ("move my 3pm") — but nothing else can be
        # invented from thin air. No signal at all → no match.
        if time_hit:
            return round(_W_TIME_ONLY, 3), (f"starts at {query.target_hour}:00",)
        return 0.0, ()

    if time_hit:
        base = min(1.0, base + _BOOST)
        reasons.append("time of day matches")

    if getattr(event, "recurring", False):
        reasons.append("recurring series")

    confidence = min(1.0, base + _BOOST * max(0, corroboration - 1))
    return round(confidence, 3), tuple(reasons)
