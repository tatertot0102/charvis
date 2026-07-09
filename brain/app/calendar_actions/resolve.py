"""Match a parsed update/delete request to the likely calendar event — pure and unit-testable.

Given the events already fetched by the caller and the hints from parse.py, decide whether the
request points at exactly one event (SINGLE), several (AMBIGUOUS → the caller asks which one), or
none (NONE). Deliberately conservative: when unsure, prefer AMBIGUOUS/NONE over guessing a write.
"""
from __future__ import annotations

import re
from datetime import time

from app.calendar_actions.schema import ParsedRequest, ResolveResult, Resolution

_WORD = re.compile(r"[a-z0-9]{2,}")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall((text or "").lower()))


def _hint_matches(hint: str, event_summary: str) -> bool:
    hint_tokens = _tokens(hint)
    if not hint_tokens:
        return False
    return hint_tokens <= _tokens(event_summary)


def _time_matches(target: time, event_start: object) -> bool:
    # event_start is a timezone-aware datetime; match on local hour (minute if the user gave one).
    hour = getattr(event_start, "hour", None)
    minute = getattr(event_start, "minute", None)
    if hour is None:
        return False
    if target.minute:
        return hour == target.hour and minute == target.minute
    return hour == target.hour


def resolve_target(request: ParsedRequest, events: list) -> ResolveResult:
    """Pick the event an update/delete refers to. `events` are CalendarEvents (timed + all-day)."""
    # Only timed events are movable/cancellable targets here (all-day handling is out of scope).
    candidates = [e for e in events if not getattr(e, "all_day", False)]

    if request.target_hint:
        candidates = [e for e in candidates if _hint_matches(request.target_hint, e.summary)]
    if request.target_time is not None:
        candidates = [e for e in candidates if _time_matches(request.target_time, e.start)]

    if len(candidates) == 1:
        return ResolveResult(Resolution.SINGLE, event=candidates[0])
    if len(candidates) > 1:
        return ResolveResult(Resolution.AMBIGUOUS, candidates=tuple(candidates))
    return ResolveResult(Resolution.NONE)
