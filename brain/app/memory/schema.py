"""In-memory dataclasses used by the consolidation pipeline (gather → derive → persist).

These are the pure, DB-free shapes the derivation logic produces and the store consumes. Keeping
them separate from the ORM models lets the derivation be unit-tested with no database.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class SourceRef:
    """One concrete piece of evidence, so any conclusion is traceable back to a record."""

    source: str  # gmail | calendar | capture | telegram | waiting | people
    ref: str  # an id/thread/handle for the underlying record
    label: str  # a human-readable descriptor ("email: ARISE onboarding")
    when: datetime | None = None

    def as_dict(self) -> dict:
        return {
            "source": self.source,
            "ref": self.ref,
            "label": self.label,
            "when": self.when.isoformat() if self.when else None,
        }


@dataclass
class Evidence:
    """The full evidence behind a conclusion: per-source counts plus the concrete records."""

    records: list[SourceRef] = field(default_factory=list)

    def add(self, ref: SourceRef) -> None:
        self.records.append(ref)

    @property
    def by_source(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for record in self.records:
            counts[record.source] = counts.get(record.source, 0) + 1
        return counts

    @property
    def source_list(self) -> list[str]:
        # Distinct sources, in first-seen order — the auditable "where this came from".
        seen: list[str] = []
        for record in self.records:
            if record.source not in seen:
                seen.append(record.source)
        return seen

    def as_dict(self, max_records: int = 25) -> dict:
        return {
            "by_source": self.by_source,
            "records": [r.as_dict() for r in self.records[:max_records]],
        }


@dataclass(frozen=True)
class DerivedConclusion:
    kind: str  # project | person | preference | relationship
    subject: str
    statement: str
    confidence: float
    evidence: Evidence
    contexts: tuple[str, ...] = ()  # context names this entity belongs to (overlapping)
    display_name: str | None = None  # human label for graph nodes (a person's name vs their email)


@dataclass(frozen=True)
class DerivedPattern:
    pattern_type: str  # response_time | activity_window | recurring_contact | recurring_project
    subject: str
    description: str
    confidence: float
    evidence: Evidence


@dataclass(frozen=True)
class DerivedCommitment:
    dedupe_key: str
    direction: str  # owed_by_me | owed_to_me | deadline
    description: str
    confidence: float
    evidence: Evidence
    counterparty: str | None = None
    due_at: datetime | None = None


@dataclass(frozen=True)
class MemorySet:
    """Everything one consolidation run derived — handed to the store as a unit."""

    conclusions: tuple[DerivedConclusion, ...] = ()
    patterns: tuple[DerivedPattern, ...] = ()
    commitments: tuple[DerivedCommitment, ...] = ()
