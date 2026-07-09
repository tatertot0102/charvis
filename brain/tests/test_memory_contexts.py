"""Unit tests for overlapping context classification (Phase 2C.5)."""
from app.memory import contexts


def test_entity_can_belong_to_multiple_contexts():
    hits = contexts.classify_text("research lab paper and coding the robot firmware")
    assert "Research" in hits
    assert "Engineering" in hits  # overlapping, not a single category


def test_college_application_keywords():
    hits = contexts.classify_text("Common App essay for Union College early decision")
    assert "College Applications" in hits


def test_finance_keywords():
    assert "Finance" in contexts.classify_text("your invoice payment is due")


def test_no_match_returns_empty():
    assert contexts.classify_text("zzz qqq") == {}


def test_edu_domain_suggests_school_and_research():
    hits = contexts.classify_email("prof@stanford.edu")
    assert "School" in hits
    assert "Research" in hits


def test_non_edu_domain_no_hint():
    assert contexts.classify_email("someone@gmail.com") == {}


def test_canonical_contexts_are_overlapping_set():
    # Sanity: the seeded contexts include the overlapping domains the spec calls for.
    for name in ("Work", "School", "Engineering", "Research", "College Applications", "Family"):
        assert name in contexts.CANONICAL_CONTEXTS
