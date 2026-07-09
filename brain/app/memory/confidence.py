"""Confidence scoring (Phase 2C.5) — a derived, explainable number, never an opaque one.

Confidence is computed from the evidence, so every score can be traced back to "because: N gmail
threads · M calendar events · …". The model is a noisy-OR over independent evidence sources: each
source contributes a saturating belief mass (more records of the same kind add less), then the
sources combine so that agreement *across* sources (email AND calendar AND a note) pushes confidence
up faster than piling on one source. Nothing is ever certain — the score is capped below 1.0.
"""
from __future__ import annotations

from app.memory.schema import Evidence

# Per-record belief mass by source. Cross-source agreement (a project seen in email AND on the
# calendar AND mentioned to Jarvis) is the strongest signal, so those sources are weighted highest.
SOURCE_WEIGHT: dict[str, float] = {
    "telegram": 0.25,  # you told Jarvis directly — strong
    "capture": 0.22,  # you wrote it down
    "calendar": 0.20,  # you gave it real time
    "waiting": 0.18,  # an open loop you're tracking
    "people": 0.15,
    "gmail": 0.14,  # plentiful but noisy, so each counts for less
}
_DEFAULT_WEIGHT = 0.12
CONFIDENCE_MAX = 0.99  # never claim certainty
CONFIDENCE_MIN = 0.05


def _source_mass(source: str, count: int) -> float:
    """Saturating contribution of one source with `count` records: 1 - (1-p)^count."""
    p = SOURCE_WEIGHT.get(source, _DEFAULT_WEIGHT)
    return 1.0 - (1.0 - p) ** max(0, count)


def score(evidence: Evidence) -> float:
    """Combine per-source belief masses with a noisy-OR. Returns a value in [MIN, MAX]."""
    by_source = evidence.by_source
    if not by_source:
        return 0.0
    product_of_complements = 1.0
    for source, count in by_source.items():
        product_of_complements *= 1.0 - _source_mass(source, count)
    combined = 1.0 - product_of_complements
    return round(min(CONFIDENCE_MAX, max(CONFIDENCE_MIN, combined)), 3)


_SOURCE_NOUN = {
    "gmail": ("email thread", "email threads"),
    "calendar": ("calendar event", "calendar events"),
    "capture": ("note", "notes"),
    "telegram": ("chat mention", "chat mentions"),
    "waiting": ("open thread", "open threads"),
    "people": ("contact record", "contact records"),
}


def explain_by_source(by_source: dict[str, int]) -> str:
    """A human phrase for a per-source count map: '12 email threads · 6 calendar events'."""
    parts: list[str] = []
    for source, count in by_source.items():
        singular, plural = _SOURCE_NOUN.get(source, (source, source))
        parts.append(f"{count} {singular if count == 1 else plural}")
    return " · ".join(parts) if parts else "no supporting evidence"


def explain(evidence: Evidence) -> str:
    """A human phrase for the evidence: '12 email threads · 6 calendar events'."""
    return explain_by_source(evidence.by_source)
