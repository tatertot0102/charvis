"""The Unified Knowledge Engine (Phase 2D.3 integration) — the single place questions are answered.

Every request becomes: resolve entities → run the relevant providers in parallel → merge into one
WorldModel → cross-check realities → detect conflicts → attach live source status → confidence. No
subsystem answers on its own anymore; they are all providers feeding this. The conversation layer and
(later) the dashboard consume the WorldModel this returns — never a provider directly.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from app.knowledge import entities as entity_resolver
from app.knowledge.model import Conflict, EntityRef, Fact, WorldModel
from app.knowledge.providers import ALL_PROVIDERS, Query, SnapshotProvider
from app.sources import registry
from app.telemetry import get_logger

log = get_logger(__name__)

# Which providers participate per intent. Every relevant provider is always searched, then merged.
_INTENT_PROVIDERS = {
    "schedule": {"calendar", "gmail", "commitment", "memory", "pattern", "waiting"},
    "entity": {"calendar", "gmail", "commitment", "memory", "pattern", "waiting", "conversation"},
    "verify": {"calendar"},
    "email_events": {"gmail", "calendar"},
}
_DEFAULT_PROVIDERS = {"calendar", "gmail", "commitment", "memory", "pattern", "waiting"}

_BUCKET = {
    "event": "events", "email": "emails", "commitment": "commitments",
    "conclusion": "memory", "pattern": "patterns", "waiting": "waiting", "message": "messages",
}


async def query(
    *,
    intent: str,
    subjects: list[str] | tuple[str, ...] = (),
    people: list[str] | tuple[str, ...] = (),
    projects: list[str] | tuple[str, ...] = (),
    places: list[str] | tuple[str, ...] = (),
    date_range: tuple[datetime, datetime] | None = None,
    text: str = "",
    person: str | None = None,
    account: str = "default",
    verify: bool = True,
    include_sources: bool = True,
    minimum_confidence: float = 0.0,
) -> WorldModel:
    """Build the merged WorldModel for a request. This is the ONE public entry point."""
    names = [*subjects, *people, *projects, *places]
    refs, terms = await _resolve_entities(names, account)

    start, end = (date_range or (None, None))
    q = Query(
        intent=intent, account=account, start=start, end=end, text=text,
        terms=terms, person=person,
    )

    provider_names = _INTENT_PROVIDERS.get(intent, _DEFAULT_PROVIDERS)
    providers = [p for p in ALL_PROVIDERS if p.name in provider_names]
    results = await asyncio.gather(*(p.fetch(q) for p in providers))
    facts: list[Fact] = [f for group in results for f in group]

    reports = await registry.all_reports(account) if include_sources else {}

    # Fallback: if the live calendar is unreachable but we asked for events, use the snapshot cache.
    if intent in ("schedule", "verify") and not any(f.kind == "event" for f in facts):
        cal_report = reports.get("calendar")
        if cal_report is None or not cal_report.connected:
            facts += await SnapshotProvider().fetch(q)

    world = WorldModel(intent=intent, query_text=text, date_range=date_range, entities=refs)
    world.sources = reports
    _merge(world, facts, minimum_confidence)
    _dedupe_events(world)
    world.conflicts = _detect_conflicts(world, refs, terms)
    world.confidence = _confidence(world)
    world.missing_information = _missing(world, reports, intent, verify)
    log.info(
        "knowledge_query", intent=intent, entities=len(refs),
        facts=len(world.all_facts()), conflicts=len(world.conflicts),
    )
    return world


async def _resolve_entities(
    names: list[str], account: str
) -> tuple[list[EntityRef], list[str]]:
    refs: list[EntityRef] = []
    terms: set[str] = set()
    for name in names:
        if not name or not name.strip():
            continue
        ref = await entity_resolver.resolve_name(name, account)
        refs.append(
            ref or EntityRef(canonical_name=name.strip(), entity_type="unknown")
        )
        terms.update(entity_resolver.match_terms(name, ref))
    return refs, [t for t in terms if t]


def _merge(world: WorldModel, facts: list[Fact], minimum_confidence: float) -> None:
    for fact in facts:
        if fact.confidence < minimum_confidence:
            world.unknowns.append(f"(low confidence {fact.confidence:.2f}) {fact.text}")
            continue
        bucket = _BUCKET.get(fact.kind)
        if bucket is not None:
            getattr(world, bucket).append(fact)


def _dedupe_events(world: WorldModel) -> None:
    seen: set[str] = set()
    deduped: list[Fact] = []
    for fact in sorted(world.events, key=lambda f: (-f.reality.rank, f.when or datetime.max)):
        key = fact.provider_object_id or fact.text
        if key in seen:
            continue
        seen.add(key)
        deduped.append(fact)
    deduped.sort(key=lambda f: f.when or datetime.max)
    world.events = deduped


def _detect_conflicts(
    world: WorldModel, refs: list[EntityRef], terms: list[str]
) -> list[Conflict]:
    """Surface a remembered recurring commitment that the calendar cannot confirm (behavior 8).

    Matches on the commitment's ENTITY name (not its schedule text) so "ECE ML Lab weekdays 10–2"
    is confirmed by an event *titled* ECE ML Lab, and only flagged when no such event exists.
    """
    conflicts: list[Conflict] = []
    for fact in world.commitments:
        if not (fact.data.get("recurrence") or fact.data.get("schedule")):
            continue
        entity = fact.entity or ""
        tokens = entity_resolver.significant_tokens(entity)
        if any(_event_mentions(e, entity, tokens) for e in world.events):
            continue
        conflicts.append(
            Conflict(
                entity=entity or "this commitment",
                kind="schedule",
                explanation=(
                    f"You told me {fact.text}, but I can't verify matching events in "
                    f"Google Calendar."
                ),
                facts=[fact],
            )
        )
    return conflicts


def _event_mentions(event: Fact, entity: str, tokens: list[str]) -> bool:
    hay = (event.text + " " + str(event.data.get("summary", ""))).lower()
    if entity and entity.lower() in hay:
        return True
    return bool(tokens) and all(t in hay for t in tokens[:3])


def _confidence(world: WorldModel) -> float:
    facts = world.all_facts()
    if not facts:
        return 0.0
    base = max(f.confidence for f in facts)
    if world.conflicts:
        base = min(base, 0.6)  # an unresolved conflict caps how sure we can be
    return round(base, 2)


def _missing(world: WorldModel, reports: dict, intent: str, verify: bool) -> list[str]:
    missing: list[str] = []
    for name, report in reports.items():
        if not report.connected:
            missing.append(f"{name} is {report.status.value} ({report.detail})")
    if verify and intent in ("schedule", "verify") and not world.events:
        cal = reports.get("calendar")
        if cal is not None and cal.connected:
            missing.append("no calendar events found in the requested range")
    return missing
