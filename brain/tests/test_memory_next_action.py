"""Unit tests for the memory-aware next-action hint (monkeypatched store; no DB)."""
from dataclasses import dataclass

from app.memory import next_action, store


@dataclass
class _Commit:
    direction: str
    description: str
    confidence: float


async def test_prefers_owed_by_me_then_confidence(monkeypatch):
    async def fake(account="default", direction=None):
        return [
            _Commit("owed_to_me", "Follow up with Bob", 0.9),
            _Commit("owed_by_me", "Reply to Dana", 0.6),
            _Commit("deadline", "Grant due", 0.8),
        ]

    monkeypatch.setattr(store, "list_commitments", fake)
    assert await next_action.suggest_from_memory() == "Reply to Dana"


async def test_ignores_low_confidence(monkeypatch):
    async def fake(account="default", direction=None):
        return [_Commit("owed_by_me", "Reply to Dana", 0.1)]

    monkeypatch.setattr(store, "list_commitments", fake)
    assert await next_action.suggest_from_memory() is None


async def test_none_when_empty(monkeypatch):
    async def fake(account="default", direction=None):
        return []

    monkeypatch.setattr(store, "list_commitments", fake)
    assert await next_action.suggest_from_memory() is None


async def test_store_error_degrades_to_none(monkeypatch):
    async def boom(account="default", direction=None):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "list_commitments", boom)
    assert await next_action.suggest_from_memory() is None
