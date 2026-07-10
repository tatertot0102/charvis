"""Unit tests for the Unified Knowledge Engine + entity resolution (Phase 2D.3 integration)."""
from datetime import UTC, datetime



from app.knowledge import engine, entities
from app.knowledge.model import Fact, Reality
from app.sources import registry
from app.sources.registry import CALENDAR, GMAIL, SourceReport, SourceStatus

_DT = datetime(2026, 7, 15, 10, 0, tzinfo=UTC)


def _connected():
    def r(name):
        return SourceReport(name=name, status=SourceStatus.CONNECTED, detail="ok")

    return {CALENDAR: r(CALENDAR), GMAIL: r(GMAIL)}


class _Fake:
    def __init__(self, name, facts):
        self.name = name
        self._facts = facts

    async def fetch(self, q):
        return list(self._facts)


def _patch(monkeypatch, providers):
    monkeypatch.setattr(engine, "ALL_PROVIDERS", providers)

    async def allr(account="default"):
        return _connected()

    monkeypatch.setattr(registry, "all_reports", allr)


def _event(summary, eid):
    return Fact(kind="event", reality=Reality.VERIFIED, text=f"{summary} — Jul 15",
                source="calendar", provider_object_id=eid, confidence=0.95, when=_DT,
                data={"summary": summary})


def _commitment(entity, *, recurrence="RRULE:FREQ=WEEKLY"):
    return Fact(kind="commitment", reality=Reality.REMEMBERED,
                text=f"{entity}: weekdays 10-2", source="commitment", entity=entity,
                confidence=0.7, data={"recurrence": recurrence, "schedule": "weekdays 10-2"})


async def test_merges_providers_and_labels_realities(monkeypatch):
    email = Fact(kind="email", reality=Reality.LIKELY, text="ARISE invite", source="gmail",
                 provider_object_id="g1", confidence=0.6)
    _patch(monkeypatch, [
        _Fake("calendar", [_event("ARISE Review", "e1")]),
        _Fake("commitment", [_commitment("ARISE Review")]),
        _Fake("gmail", [email]),
    ])
    world = await engine.query(intent="schedule", date_range=(_DT, _DT))
    assert len(world.events) == 1 and len(world.commitments) == 1 and len(world.emails) == 1
    assert world.by_reality(Reality.VERIFIED)[0].provider_object_id == "e1"
    # The event titled "ARISE Review" confirms the commitment → no conflict.
    assert world.conflicts == []


async def test_conflict_when_commitment_has_no_verifying_event(monkeypatch):
    _patch(monkeypatch, [
        _Fake("calendar", []),
        _Fake("commitment", [_commitment("ECE Machine Learning Lab")]),
    ])
    world = await engine.query(intent="schedule", date_range=(_DT, _DT))
    assert len(world.conflicts) == 1
    assert "can't verify" in world.conflicts[0].explanation
    assert world.confidence <= 0.6  # an unresolved conflict caps confidence


async def test_dedupe_events_by_provider_id(monkeypatch):
    _patch(monkeypatch, [
        _Fake("calendar", [_event("Standup", "dup"), _event("Standup", "dup")]),
    ])
    world = await engine.query(intent="schedule", date_range=(_DT, _DT))
    assert len(world.events) == 1


async def test_minimum_confidence_moves_low_facts_to_unknowns(monkeypatch):
    weak = Fact(kind="email", reality=Reality.LIKELY, text="maybe", source="gmail",
                provider_object_id="g9", confidence=0.2)
    _patch(monkeypatch, [_Fake("gmail", [weak])])
    world = await engine.query(intent="entity", subjects=["x"], minimum_confidence=0.5)
    assert world.emails == []
    assert any("low confidence" in u for u in world.unknowns)


# --- canonical entity resolution + permanent corrections ---------------------


async def test_record_correction_aliases_old_name_forever():
    # "It is ECE Machine Learning Lab" when the prior referent was "ARISE".
    ref = await entities.record_correction("ARISE", "ECE Machine Learning Lab")
    assert ref.canonical_name == "ECE Machine Learning Lab"
    resolved = await entities.resolve_name("ARISE")
    assert resolved is not None
    assert resolved.canonical_name == "ECE Machine Learning Lab"


async def test_resolve_unknown_name_returns_none():
    assert await entities.resolve_name("totally-unknown-thing-xyz") is None


async def test_match_terms_includes_aliases():
    ref = await entities.record_correction("DSI", "Data Science Institute")
    terms = entities.match_terms("DSI", ref)
    assert "dsi" in terms and "data science institute" in terms
