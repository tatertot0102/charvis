"""The unified World Model and its parts (Phase 2D.3 integration).

Every question builds one of these BEFORE any prose. Facts are never bare: each carries a reality
label (was it verified against a provider, merely likely, remembered from the user, or inferred from a
pattern?) and a link to the record it came from. Providers produce Facts; the engine merges them into
a WorldModel; the renderer (or a future dashboard) reads the WorldModel. Nothing skips this structure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum


class Reality(str, Enum):
    """How much we trust a fact — never mix these in an answer (Golden Rule #7)."""

    VERIFIED = "verified"      # backed by a live provider object (Calendar event, Gmail message)
    LIKELY = "likely"          # strong signal not yet provider-confirmed (an email invitation)
    REMEMBERED = "remembered"  # the user explicitly told Jarvis (a commitment / memory conclusion)
    INFERRED = "inferred"      # derived from a detected pattern

    @property
    def rank(self) -> int:
        return {"verified": 3, "likely": 2, "remembered": 1, "inferred": 0}[self.value]


@dataclass(frozen=True)
class EntityRef:
    """A canonical thing (person/project/place/commitment) that several providers may reference."""

    canonical_name: str
    entity_type: str
    aliases: tuple[str, ...] = ()
    entity_id: int | None = None


@dataclass
class Fact:
    """One structured claim from one provider. No prose, no LLM — just evidence."""

    kind: str  # event | email | commitment | conclusion | pattern | waiting | message
    reality: Reality
    text: str  # short structured description (a line, not a paragraph)
    source: str  # provider name
    entity: str | None = None  # canonical entity this fact is about
    provider: str | None = None  # google | gmail | …
    provider_object_id: str | None = None  # real event/message id when reality == VERIFIED/LIKELY
    confidence: float = 0.5
    when: datetime | None = None
    data: dict = field(default_factory=dict)


@dataclass
class Conflict:
    """A surfaced disagreement between two realities about the same entity — never resolved silently."""

    entity: str
    kind: str  # schedule | presence | value
    explanation: str
    facts: list[Fact] = field(default_factory=list)


@dataclass
class WorldModel:
    """The merged, source-preserving picture the whole system answers from."""

    intent: str
    query_text: str = ""
    date_range: tuple[datetime, datetime] | None = None
    entities: list[EntityRef] = field(default_factory=list)
    events: list[Fact] = field(default_factory=list)
    emails: list[Fact] = field(default_factory=list)
    commitments: list[Fact] = field(default_factory=list)
    memory: list[Fact] = field(default_factory=list)      # remembered conclusions
    patterns: list[Fact] = field(default_factory=list)     # inferred
    waiting: list[Fact] = field(default_factory=list)
    messages: list[Fact] = field(default_factory=list)
    weather_candidates: list[Fact] = field(default_factory=list)  # reserved; no provider yet
    transit_candidates: list[Fact] = field(default_factory=list)   # reserved; no provider yet
    conflicts: list[Conflict] = field(default_factory=list)
    sources: dict = field(default_factory=dict)  # name -> SourceReport (live capability truth)
    confidence: float = 0.0
    missing_information: list[str] = field(default_factory=list)
    unknowns: list[str] = field(default_factory=list)

    def all_facts(self) -> list[Fact]:
        return [
            *self.events, *self.emails, *self.commitments, *self.memory,
            *self.patterns, *self.waiting, *self.messages,
        ]

    def by_reality(self, reality: Reality) -> list[Fact]:
        return [f for f in self.all_facts() if f.reality is reality]

    def has_facts(self) -> bool:
        return bool(self.all_facts())

    def to_dict(self) -> dict:
        """JSON-serializable form — what the dashboard consumes (same WorldModel, no extra logic)."""
        def fact(f: Fact) -> dict:
            return {
                "kind": f.kind, "reality": f.reality.value, "text": f.text, "source": f.source,
                "entity": f.entity, "provider": f.provider,
                "provider_object_id": f.provider_object_id, "confidence": f.confidence,
                "when": f.when.isoformat() if f.when else None,
            }

        return {
            "intent": self.intent,
            "query_text": self.query_text,
            "date_range": [d.isoformat() for d in self.date_range] if self.date_range else None,
            "entities": [
                {"canonical_name": e.canonical_name, "entity_type": e.entity_type,
                 "aliases": list(e.aliases)} for e in self.entities
            ],
            "events": [fact(f) for f in self.events],
            "emails": [fact(f) for f in self.emails],
            "commitments": [fact(f) for f in self.commitments],
            "memory": [fact(f) for f in self.memory],
            "patterns": [fact(f) for f in self.patterns],
            "waiting": [fact(f) for f in self.waiting],
            "messages": [fact(f) for f in self.messages],
            "conflicts": [
                {"entity": c.entity, "kind": c.kind, "explanation": c.explanation}
                for c in self.conflicts
            ],
            "sources": {
                name: {"status": r.status.value, "connected": r.connected, "detail": r.detail}
                for name, r in self.sources.items()
            },
            "confidence": self.confidence,
            "missing_information": self.missing_information,
            "unknowns": self.unknowns,
        }
