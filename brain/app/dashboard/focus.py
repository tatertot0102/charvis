"""User focus emphasis (Phase 2F.0) — pure, and it never hides objective urgency.

Focus changes EMPHASIS, not reality. "Show college and Dana prep, not ARISE" re-ranks supporting
information toward the focus area, but an urgent objective fact (an imminent event, an expiring
approval) can never be demoted or hidden by a focus preference. Objective reality and user focus stay
clearly distinct.
"""
from __future__ import annotations

import re

from app.dashboard.contracts import PriorityItem

_STRIP = re.compile(r"[^a-z0-9\s]")


def _tokens(text: str | None) -> set[str]:
    if not text:
        return set()
    return {t for t in _STRIP.sub(" ", text.lower()).split() if len(t) > 2}


def _matches_focus(item: PriorityItem, focus_tokens: set[str]) -> bool:
    if not focus_tokens:
        return False
    hay = _tokens(item.title) | _tokens(item.reason) | _tokens(item.context)
    for ev in item.evidence:
        hay |= _tokens(ev.text)
    return bool(hay & focus_tokens)


def apply_focus(items: list[PriorityItem], focus: str | None) -> list[PriorityItem]:
    """Re-rank priority items toward `focus`, keeping urgent items first no matter what.

    Sort key (stable): urgent first (objective reality wins), then focus-match, then confidence.
    No item is ever dropped — focus only reorders emphasis.
    """
    focus_tokens = _tokens(focus)

    def sort_key(item: PriorityItem) -> tuple:
        return (
            0 if item.urgent else 1,
            0 if _matches_focus(item, focus_tokens) else 1,
            -item.confidence,
        )

    return sorted(items, key=sort_key)


def rank_hero_candidates(
    candidates: list[tuple[float, bool, object]], focus: str | None
) -> list[object]:
    """Rank (priority_score, urgent, payload) hero candidates; urgent objective ones never demoted.

    `priority_score` is the objective importance (e.g. inverse time-to-event). Focus can only break
    ties among non-urgent candidates.
    """
    focus_tokens = _tokens(focus)

    def key(entry: tuple[float, bool, object]) -> tuple:
        score, urgent, payload = entry
        text = getattr(payload, "title", "") if payload is not None else ""
        focus_hit = bool(_tokens(text) & focus_tokens)
        return (0 if urgent else 1, 0 if focus_hit else 1, -score)

    return [payload for _, _, payload in sorted(candidates, key=key)]
