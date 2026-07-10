"""Rank provider events against a request and decide the resolution (Phase 2D.1) — pure/testable.

Scores every timed event with matching.score_event, drops anything below the confidence floor, and
returns a ranked ResolveResult. Deliberately conservative and non-fabricating:
  • bulk request → BULK with the whole confident set (or NONE),
  • single request → SINGLE only when exactly one confident event stands out; several → AMBIGUOUS;
    zero → NONE.
Never invents an event and never silently picks among several distinct matches.
"""
from __future__ import annotations

from app.calendar_actions import matching
from app.calendar_actions.schema import (
    ParsedRequest,
    Resolution,
    ResolveResult,
    ScoredEvent,
)


def _scored(request: ParsedRequest, events: list, min_confidence: float) -> list[ScoredEvent]:
    query = matching.build_query(request)
    out: list[ScoredEvent] = []
    for event in events:
        if getattr(event, "all_day", False):
            continue  # all-day handling is out of scope for moves/cancels
        confidence, reasons = matching.score_event(query, event)
        if confidence >= min_confidence:
            out.append(ScoredEvent(event=event, confidence=confidence, reasons=reasons))
    # Highest confidence first; ties keep chronological order (events arrive start-sorted).
    out.sort(key=lambda s: s.confidence, reverse=True)
    return out


def resolve(
    request: ParsedRequest, events: list, *, min_confidence: float, bulk: bool | None = None
) -> ResolveResult:
    """Rank matches and classify the resolution. `events` are provider-backed CalendarEvents."""
    is_bulk = request.bulk if bulk is None else bulk
    matches = _scored(request, events, min_confidence)

    if not matches:
        return ResolveResult(Resolution.NONE)
    if is_bulk:
        return ResolveResult(Resolution.BULK, matches=tuple(matches))
    if len(matches) == 1:
        return ResolveResult(Resolution.SINGLE, matches=tuple(matches))
    return ResolveResult(Resolution.AMBIGUOUS, matches=tuple(matches))
