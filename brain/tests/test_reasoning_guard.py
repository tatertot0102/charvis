"""The Grounded Reasoning Layer (Phase 2D.4): compose over evidence, never fabricate.

The guard is the structural backstop for Golden Rule #7 — ungrounded times/dates and affirmations of
absent events are rejected, and rejection degrades to the safe deterministic renderer.
"""
from datetime import UTC, datetime

from app import reasoning
from app.knowledge.model import Fact, Reality, WorldModel
from app.reasoning import guard, reason
from app.reasoning.collect import GroundedContext


def _world_with_lab() -> WorldModel:
    world = WorldModel(intent="entity", query_text="ECE Machine Learning Lab")
    world.events.append(
        Fact(
            kind="event", reality=Reality.VERIFIED,
            text="ECE Machine Learning Lab — Mon Jun 1 10:00 AM",
            source="calendar", when=datetime(2026, 6, 1, 10, 0, tzinfo=UTC),
            data={"summary": "ECE Machine Learning Lab"},
        )
    )
    return world


def _ctx(kind: str = "entity", world: WorldModel | None = None) -> GroundedContext:
    return GroundedContext(
        question="what is my lab", kind=kind, world=world or _world_with_lab()
    )


def test_guard_passes_grounded_time():
    # "10 AM" canonicalizes to the same key as the grounded "10:00 AM"
    out = guard.validate("Your ECE Machine Learning Lab starts around 10 AM.", _ctx())
    assert out is not None


def test_guard_rejects_ungrounded_time():
    assert guard.validate("Your lab runs from 3 PM to 5 PM.", _ctx()) is None


def test_guard_rejects_ungrounded_date():
    assert guard.validate("There's a session on June 5.", _ctx()) is None


def test_guard_rejects_affirming_absent_event():
    empty = WorldModel(intent="verify")
    ctx = _ctx(kind="verify", world=empty)
    assert guard.validate("Yes, it's on your calendar this Tuesday.", ctx) is None


def test_guard_rejects_false_write_claim():
    assert guard.validate("I've added the lab to your calendar.", _ctx()) is None


async def test_narrate_falls_back_under_echo_provider():
    # default test provider is echo → reasoning unavailable → deterministic fallback verbatim
    out = await reasoning.narrate(
        _world_with_lab(), kind="entity", question="x", fallback=lambda: "DETERMINISTIC"
    )
    assert out == "DETERMINISTIC"


async def test_narrate_returns_grounded_prose(monkeypatch):
    monkeypatch.setattr(reason, "reasoning_available", lambda: True)

    async def _fake_generate(messages):
        return "You have ECE Machine Learning Lab, and it starts around 10 AM."

    monkeypatch.setattr(reason, "_generate", _fake_generate)
    out = await reasoning.narrate(
        _world_with_lab(), kind="entity", question="what is my lab",
        fallback=lambda: "DETERMINISTIC",
    )
    assert "ECE Machine Learning Lab" in out
    assert out != "DETERMINISTIC"


async def test_narrate_falls_back_when_prose_fabricates(monkeypatch):
    monkeypatch.setattr(reason, "reasoning_available", lambda: True)

    async def _fake_generate(messages):
        return "Your lab is at 3 PM sharp on Friday June 9."  # ungrounded time+date

    monkeypatch.setattr(reason, "_generate", _fake_generate)
    out = await reasoning.narrate(
        _world_with_lab(), kind="entity", question="what is my lab",
        fallback=lambda: "DETERMINISTIC",
    )
    assert out == "DETERMINISTIC"
