"""The Unified Knowledge Engine (Phase 2D.3 integration) — the single entry point for answers.

Nothing should bypass this package. A caller asks `knowledge.query(...)`, gets back a WorldModel that
merges every relevant provider (Calendar, Gmail, Commitments, Memory, Patterns, Waiting, Conversation)
with reality labels, conflicts, live source status, and confidence — then renders it. Corrections the
user makes are recorded here as permanent entity aliases so future queries resolve automatically.
"""
from app.knowledge import entities, render
from app.knowledge.engine import query
from app.knowledge.model import Conflict, EntityRef, Fact, Reality, WorldModel

__all__ = [
    "query",
    "render",
    "entities",
    "WorldModel",
    "Fact",
    "Reality",
    "Conflict",
    "EntityRef",
]
