"""StructuredAnswer — the audited answer built from evidence BEFORE any prose (Phase 2D.3).

The core discipline: never let the model turn a question into a sentence directly. A handler first
assembles what is actually known — which sources are reachable, which facts come from a real provider
object, which come from the user, what's missing — and only then renders prose. Provider facts and
user-stated facts are kept in separate buckets so a thing you told Jarvis can never be presented as
something its calendar or inbox confirmed. The validator (query.validate) checks the prose against
this structure.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime

from app.sources.registry import SourceReport


@dataclass(frozen=True)
class ProviderFact:
    """A fact backed by a real provider object (a Calendar event id, a Gmail message id)."""

    source: str  # "calendar" | "gmail"
    provider_object_id: str
    text: str
    when: datetime | None = None


@dataclass(frozen=True)
class UserFact:
    """Something the user told Jarvis — never presented as provider-confirmed truth."""

    text: str
    origin: str = "user_statement"


@dataclass
class StructuredAnswer:
    """Everything known about a question, bucketed by provenance, plus a deterministic renderer."""

    question: str
    intent: str
    headline: str | None = None
    time_range: dict | None = None
    source_status: list[SourceReport] = field(default_factory=list)
    provider_facts: list[ProviderFact] = field(default_factory=list)
    user_facts: list[UserFact] = field(default_factory=list)
    derived_facts: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    missing_information: list[str] = field(default_factory=list)
    suggested_actions: list[str] = field(default_factory=list)
    empty_state: str | None = None  # shown when there are no provider facts and no user facts

    def provider_object_ids(self) -> set[str]:
        return {f.provider_object_id for f in self.provider_facts if f.provider_object_id}

    def has_content(self) -> bool:
        return bool(self.provider_facts or self.user_facts or self.derived_facts)

    def render(self) -> str:
        """Deterministic prose assembled only from the structured buckets above."""
        parts: list[str] = []
        if self.headline:
            parts.append(self.headline)

        if self.provider_facts:
            parts.append("\n".join(f"• {f.text}" for f in self.provider_facts))
        elif not self.user_facts and self.empty_state:
            parts.append(self.empty_state)

        if self.user_facts:
            # Framed explicitly as user-stated so it is never mistaken for provider truth.
            lead = "From what you've told me (not confirmed by your calendar or email):"
            parts.append("\n".join([lead, *(f"• {f.text}" for f in self.user_facts)]))

        if self.conflicts:
            parts.append("\n".join(self.conflicts))

        if self.suggested_actions:
            parts.append("\n".join(self.suggested_actions))

        return "\n\n".join(p for p in parts if p).strip()
