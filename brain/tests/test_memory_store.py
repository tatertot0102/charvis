"""Integration tests for memory persistence + reads (requires the test Postgres, migrated)."""
from datetime import UTC, datetime

from app.memory import store
from app.memory.schema import (
    DerivedCommitment,
    DerivedConclusion,
    DerivedPattern,
    Evidence,
    MemorySet,
    SourceRef,
)

ACCOUNT = "acct-store-test"
NOW = datetime(2026, 7, 1, tzinfo=UTC)


def _evidence(**by_source: int) -> Evidence:
    ev = Evidence()
    for source, count in by_source.items():
        for i in range(count):
            ev.add(SourceRef(source, f"{source}-{i}", f"{source} {i}", NOW))
    return ev


def _memory_set() -> MemorySet:
    return MemorySet(
        conclusions=(
            DerivedConclusion(
                kind="project", subject="ARISE", statement="“ARISE” is an active project.",
                confidence=0.94, evidence=_evidence(gmail=12, calendar=6),
                contexts=("Research", "Engineering"),
            ),
        ),
        patterns=(
            DerivedPattern(
                pattern_type="response_time", subject="dana@lab.org",
                description="You usually reply to Dana within a day.",
                confidence=0.7, evidence=_evidence(gmail=4),
            ),
        ),
        commitments=(
            DerivedCommitment(
                dedupe_key="waiting:t1", direction="owed_by_me",
                description="Reply to Dana about the budget.",
                confidence=0.6, evidence=_evidence(waiting=1, gmail=1),
                counterparty="dana@lab.org",
            ),
        ),
    )


async def test_persist_then_read_back():
    result = await store.persist(_memory_set(), ACCOUNT)
    assert result.conclusions == 1
    assert result.context_tags == 2  # Research + Engineering

    conclusions = await store.list_conclusions(account=ACCOUNT)
    arise = next(c for c in conclusions if c.subject == "ARISE")
    assert arise.confidence == 0.94
    assert arise.evidence["by_source"]["gmail"] == 12
    assert "gmail" in arise.source_list

    tags = await store.contexts_for_entity("ARISE", account=ACCOUNT)
    names = {name for name, _ in tags}
    assert {"Research", "Engineering"} <= names  # overlapping contexts persisted

    patterns = await store.list_patterns(account=ACCOUNT)
    assert any(p.subject == "dana@lab.org" for p in patterns)

    commitments = await store.list_commitments(account=ACCOUNT, direction="owed_by_me")
    assert any(c.dedupe_key is not None and "budget" in c.description for c in commitments)


async def test_persist_is_idempotent():
    await store.persist(_memory_set(), "acct-idem")
    first = await store.list_conclusions(account="acct-idem")
    original_first_seen = first[0].first_seen
    await store.persist(_memory_set(), "acct-idem")  # re-run
    second = await store.list_conclusions(account="acct-idem")
    assert len(second) == len(first) == 1  # no duplicate row
    assert second[0].first_seen == original_first_seen  # first_seen preserved


async def test_reconsolidation_prunes_unsupported_conclusions():
    await store.persist(_memory_set(), "acct-prune")  # stores project ARISE
    # A later run no longer derives ARISE — it derives a different project instead.
    replacement = MemorySet(
        conclusions=(
            DerivedConclusion(
                kind="project", subject="BOREALIS", statement="“BOREALIS” is an active project.",
                confidence=0.8, evidence=_evidence(gmail=8), contexts=("Research",),
            ),
        ),
    )
    await store.persist(replacement, "acct-prune")
    subjects = {c.subject for c in await store.list_conclusions(account="acct-prune")}
    assert "BOREALIS" in subjects
    assert "ARISE" not in subjects  # stale conclusion pruned
    # Its context tags are gone too (no orphaned tags).
    assert await store.contexts_for_entity("ARISE", account="acct-prune") == []


async def test_empty_run_does_not_wipe_memory():
    await store.persist(_memory_set(), "acct-empty")
    await store.persist(MemorySet(), "acct-empty")  # a transient empty derivation
    subjects = {c.subject for c in await store.list_conclusions(account="acct-empty")}
    assert "ARISE" in subjects  # guarded: empty run must not delete good memory


async def test_find_conclusion_and_confidence_band():
    await store.persist(_memory_set(), "acct-find")
    assert (await store.find_conclusion("arise", account="acct-find")) is not None
    high = await store.list_conclusions(account="acct-find", min_confidence=0.9)
    assert high and all(c.confidence >= 0.9 for c in high)
    low = await store.list_conclusions(account="acct-find", max_confidence=0.5)
    assert all(c.confidence < 0.5 for c in low)
