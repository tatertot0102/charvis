"""Unit tests for confidence scoring — derived from and explained by evidence (Phase 2C.5)."""
from datetime import UTC, datetime

from app.memory import confidence
from app.memory.schema import Evidence, SourceRef


def _ev(**by_source: int) -> Evidence:
    ev = Evidence()
    for source, count in by_source.items():
        for i in range(count):
            ev.add(SourceRef(source, f"{source}-{i}", f"{source} record {i}",
                             datetime(2026, 7, 1, tzinfo=UTC)))
    return ev


def test_empty_evidence_scores_zero():
    assert confidence.score(Evidence()) == 0.0


def test_more_evidence_raises_confidence():
    weak = confidence.score(_ev(gmail=1))
    strong = confidence.score(_ev(gmail=12))
    assert weak < strong


def test_cross_source_beats_single_source():
    single = confidence.score(_ev(gmail=6))
    diverse = confidence.score(_ev(gmail=3, calendar=3))
    # Agreement across independent sources should be more convincing than one source alone.
    assert diverse > single


def test_never_certain():
    assert confidence.score(_ev(gmail=100, calendar=100, telegram=100)) <= confidence.CONFIDENCE_MAX


def test_arise_example_is_high_confidence():
    # The EXECUTION_PLAN §2C.5 worked example: 12 threads + 6 events + chat + notes → very confident.
    score = confidence.score(_ev(gmail=12, calendar=6, telegram=1, capture=2))
    assert score >= 0.9


def test_explain_names_the_sources():
    text = confidence.explain(_ev(gmail=12, calendar=6))
    assert "12 email threads" in text
    assert "6 calendar events" in text


def test_explain_singular_plural():
    assert "1 calendar event" in confidence.explain(_ev(calendar=1))
    assert "2 calendar events" in confidence.explain(_ev(calendar=2))
