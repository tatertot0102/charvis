"""Unit tests for the memory chat handler — evidence surfaced, not just verdicts (no DB)."""
from dataclasses import dataclass, field

import pytest

from app.conversation import memory_handler
from app.conversation.intents import MemoryIntent
from app.memory import consolidation, store


@dataclass
class _Row:
    kind: str = "project"
    subject: str = "ARISE"
    statement: str = "“ARISE” looks like an active project — 12 email threads · 6 calendar events."
    confidence: float = 0.96
    evidence: dict = field(default_factory=lambda: {"by_source": {"gmail": 12, "calendar": 6}})
    source_list: list = field(default_factory=lambda: ["gmail", "calendar"])
    description: str = "You usually reply to Dana within a day."


@pytest.fixture(autouse=True)
def _no_consolidation(monkeypatch):
    async def noop(account="default"):
        return False

    monkeypatch.setattr(consolidation, "ensure_consolidated", noop)


async def test_why_surfaces_evidence_and_confidence(monkeypatch):
    async def fake_find(subject, account="default"):
        return _Row()

    async def fake_ctx(entity_key, account="default"):
        return [("Research", 0.9), ("Engineering", 0.8)]

    monkeypatch.setattr(store, "find_conclusion", fake_find)
    monkeypatch.setattr(store, "contexts_for_entity", fake_ctx)
    reply = await memory_handler.handle(MemoryIntent.WHY, "ARISE")
    assert "96%" in reply
    assert "12 email threads" in reply  # evidence, not just the verdict
    assert "Research" in reply


async def test_why_unknown_subject_is_honest(monkeypatch):
    async def fake_find(subject, account="default"):
        return None

    monkeypatch.setattr(store, "find_conclusion", fake_find)
    reply = await memory_handler.handle(MemoryIntent.WHY, "Atlantis")
    assert "don't have a confident view" in reply.lower()


async def test_projects_lists_evidence(monkeypatch):
    async def fake_list(account="default", kind=None, min_confidence=None, max_confidence=None):
        return [_Row()] if kind == "project" else []

    async def fake_ctx(entity_key, account="default"):
        return [("Research", 0.9)]

    monkeypatch.setattr(store, "list_conclusions", fake_list)
    monkeypatch.setattr(store, "contexts_for_entity", fake_ctx)
    reply = await memory_handler.handle(MemoryIntent.PROJECTS)
    assert "ARISE" in reply
    assert "12 email threads" in reply


async def test_patterns_reply(monkeypatch):
    async def fake_patterns(account="default"):
        return [_Row()]

    monkeypatch.setattr(store, "list_patterns", fake_patterns)
    reply = await memory_handler.handle(MemoryIntent.PATTERNS)
    assert "Dana" in reply


async def test_low_confidence_filters(monkeypatch):
    async def fake_list(account="default", kind=None, min_confidence=None, max_confidence=None):
        assert max_confidence is not None  # low-confidence query must pass a ceiling
        return [_Row(confidence=0.3, statement="“Zephyr” might be a project.")]

    monkeypatch.setattr(store, "list_conclusions", fake_list)
    reply = await memory_handler.handle(MemoryIntent.LOW_CONFIDENCE)
    assert "Zephyr" in reply
    assert "30%" in reply


async def test_handler_never_raises(monkeypatch):
    async def boom(*a, **k):
        raise RuntimeError("db down")

    monkeypatch.setattr(store, "list_conclusions", boom)
    monkeypatch.setattr(store, "list_patterns", boom)
    monkeypatch.setattr(store, "list_commitments", boom)
    reply = await memory_handler.handle(MemoryIntent.KNOW_ABOUT_ME)
    assert isinstance(reply, str) and reply
