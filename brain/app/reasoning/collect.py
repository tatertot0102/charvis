"""Evidence collection for the reasoning layer (Phase 2D.4).

Wraps the WorldModel (live cross-source evidence) together with the durable Life Graph neighborhoods
of the entities the question is about, into one `GroundedContext`. This is the ONLY thing the reasoner
is allowed to see — the LLM reasons over this and nothing else, which is what keeps it honest. The
context also exposes a normalized `grounding_text` the truth guard checks the generated prose against.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.knowledge.model import Reality, WorldModel
from app.lifemodel import graph
from app.telemetry import get_logger

log = get_logger(__name__)

_REALITY_LABEL = {
    Reality.VERIFIED: "Verified (Google)",
    Reality.LIKELY: "Likely (email)",
    Reality.REMEMBERED: "Remembered (you told me)",
    Reality.INFERRED: "Inferred (a pattern)",
}


@dataclass
class GroundedContext:
    """Everything — and only what — the reasoner may use to answer one question."""

    question: str
    kind: str  # entity | schedule | verify | email_events
    world: WorldModel
    neighborhoods: list[dict] = field(default_factory=list)
    label: str | None = None  # e.g. "this month" for a schedule range

    # --- what the LLM sees (evidence only, reality-labelled) ---
    def evidence_block(self) -> str:
        lines: list[str] = []
        for fact in self.world.all_facts():
            lines.append(f"- [{_REALITY_LABEL.get(fact.reality, fact.reality.value)}] {fact.text}")
        for hood in self.neighborhoods:
            lines.append(f"\nWhat I durably know about “{hood['canonical_name']}”:")
            if hood.get("inferred_role"):
                lines.append(f"  - role/context: {hood['inferred_role']}")
            for fact in hood.get("facts", [])[:8]:
                lines.append(f"  - {fact['value']} ({fact['truth_status']})")
            for edge in hood.get("edges", [])[:8]:
                arrow = "→" if edge["direction"] == "outgoing" else "←"
                lines.append(
                    f"  - {arrow} {edge['relation_type']} {edge['other_name'] or '?'} "
                    f"({edge['other_type']})"
                )
        if not lines:
            return "(no supporting evidence found in any source)"
        return "\n".join(lines)

    def conflict_block(self) -> str:
        parts = [f"- {c.explanation}" for c in self.world.conflicts]
        for hood in self.neighborhoods:
            parts += [f"- {c['explanation']}" for c in hood.get("conflicts", [])]
        return "\n".join(parts)

    def source_block(self) -> str:
        return "\n".join(
            f"- {name}: {'connected' if r.connected else r.status.value} ({r.detail})"
            for name, r in self.world.sources.items()
        )

    def has_evidence(self) -> bool:
        return self.world.has_facts() or any(h.get("facts") for h in self.neighborhoods)

    # --- what the guard checks generated prose against ---
    def grounding_text(self) -> str:
        # Soft-normalize only: lowercase + collapse whitespace, but KEEP ':' '/' '@' '.' so the
        # guard can still find times ("10:00 am"), dates ("6/5"), and emails in the evidence.
        chunks: list[str] = [self.question]
        for fact in self.world.all_facts():
            chunks.append(fact.text)
            for key in ("summary", "subject", "from", "location"):
                val = fact.data.get(key)
                if val:
                    chunks.append(str(val))
        for entity in self.world.entities:
            chunks.append(entity.canonical_name)
            chunks.extend(entity.aliases)
        for hood in self.neighborhoods:
            chunks.append(hood["canonical_name"])
            chunks.extend(hood.get("aliases", []))
            if hood.get("inferred_role"):
                chunks.append(hood["inferred_role"])
            for fact in hood.get("facts", []):
                chunks.append(fact["value"])
                for ev in fact.get("evidence", []):
                    if ev.get("excerpt"):
                        chunks.append(ev["excerpt"])
            for edge in hood.get("edges", []):
                if edge.get("other_name"):
                    chunks.append(edge["other_name"])
        return re.sub(r"\s+", " ", " ".join(c for c in chunks if c).lower()).strip()


async def build_context(
    world: WorldModel, *, question: str, kind: str, account: str = "default",
    label: str | None = None,
) -> GroundedContext:
    """Assemble the grounded context: the live WorldModel plus each resolved entity's graph node."""
    neighborhoods: list[dict] = []
    seen: set[int] = set()
    for ref in world.entities:
        if ref.entity_id is None or ref.entity_id in seen:
            continue
        seen.add(ref.entity_id)
        try:
            hood = await graph.neighborhood(account, ref.entity_id)
        except Exception as exc:  # noqa: BLE001 — graph is best-effort context, never fatal.
            log.info("neighborhood_unavailable", error=type(exc).__name__)
            hood = None
        if hood is not None:
            neighborhoods.append(hood)
    return GroundedContext(
        question=question, kind=kind, world=world, neighborhoods=neighborhoods, label=label,
    )
