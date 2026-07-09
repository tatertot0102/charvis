"""Behavioral pattern detection (Phase 2C.5) — decision-relevant patterns only.

Three deterministic patterns are derived from existing signals:
  - response_time: how fast you typically reply to a given person (sharpens "who's waiting").
  - activity_window: when you tend to do work (informs scheduling / "what should I do next").
  - recurring_contact: who you interact with regularly (feeds priority scoring).
Trivia ("you got 84 LinkedIn emails") is never produced — promotional/no-reply traffic is excluded
upstream, and every pattern must clear a support threshold. Pure; unit-testable with no DB.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median

from app.integrations.google.classify import is_noreply
from app.memory import confidence
from app.memory.schema import DerivedPattern, Evidence, SourceRef
from app.memory.signals import Signals

MIN_RESPONSES = 2  # need at least this many replies to a person to call it a pattern
MIN_ACTIVITY_EVENTS = 4  # timestamps needed before an activity window is meaningful
ACTIVITY_SHARE = 0.34  # the top window must be at least this fraction of all activity
MIN_RECURRING_INTERACTIONS = 5  # message_count to count someone as a recurring contact


def _daypart(hour: int) -> str:
    if 5 <= hour < 12:
        return "morning"
    if 12 <= hour < 17:
        return "afternoon"
    if 17 <= hour < 22:
        return "evening"
    return "late night"


def _human_gap(delta: timedelta) -> str:
    hours = delta.total_seconds() / 3600
    if hours <= 24:
        return "within a day"
    if hours <= 72:
        return "within a few days"
    return "after about a week"


def response_time_patterns(signals: Signals) -> list[DerivedPattern]:
    """For each person, pair their inbound message with your next outbound reply in the thread."""
    by_thread: dict[str, list] = defaultdict(list)
    for email in signals.emails:
        if email.received_at is not None:
            by_thread[email.thread_id].append(email)

    gaps: dict[str, list[timedelta]] = defaultdict(list)
    refs: dict[str, Evidence] = defaultdict(Evidence)
    for thread in by_thread.values():
        ordered = sorted(thread, key=lambda e: e.received_at)
        pending: tuple[str, datetime] | None = None
        for email in ordered:
            if email.direction == "inbound" and not email.is_promotional:
                if not is_noreply(email.from_email):
                    pending = (email.from_email, email.received_at)
            elif email.direction == "outbound" and pending is not None:
                person, sent_at = pending
                gap = email.received_at - sent_at
                if gap.total_seconds() >= 0:
                    gaps[person].append(gap)
                    refs[person].add(
                        SourceRef("gmail", email.thread_id, f"reply to {person}", email.received_at)
                    )
                pending = None

    patterns: list[DerivedPattern] = []
    for person, deltas in gaps.items():
        if len(deltas) < MIN_RESPONSES:
            continue
        typical = median(deltas)
        evidence = refs[person]
        patterns.append(
            DerivedPattern(
                pattern_type="response_time",
                subject=person,
                description=f"You usually reply to {person} {_human_gap(typical)}.",
                confidence=confidence.score(evidence),
                evidence=evidence,
            )
        )
    return patterns


def activity_window_pattern(signals: Signals) -> list[DerivedPattern]:
    """When you tend to be active: outbound-email times + event start times, bucketed."""
    buckets: dict[str, Evidence] = defaultdict(Evidence)
    counts: dict[str, int] = defaultdict(int)
    total = 0

    def _record(when: datetime | None, source: str, ref: str, label: str) -> None:
        nonlocal total
        if when is None:
            return
        key = f"{when.strftime('%A')} {_daypart(when.hour)}"
        counts[key] += 1
        buckets[key].add(SourceRef(source, ref, label, when))
        total += 1

    for email in signals.emails:
        if email.direction == "outbound" and not email.is_promotional:
            _record(email.received_at, "gmail", email.thread_id, "sent email")
    for event in signals.events:
        _record(event.start, "calendar", event.event_id, f"event: {event.summary}")

    if total < MIN_ACTIVITY_EVENTS:
        return []
    top_key = max(counts, key=lambda k: counts[k])
    if counts[top_key] / total < ACTIVITY_SHARE:
        return []
    evidence = buckets[top_key]
    return [
        DerivedPattern(
            pattern_type="activity_window",
            subject=top_key,
            description=f"You're most active on {top_key}s.",
            confidence=confidence.score(evidence),
            evidence=evidence,
        )
    ]


def recurring_contact_patterns(signals: Signals) -> list[DerivedPattern]:
    """People you interact with often enough to matter for prioritization."""
    patterns: list[DerivedPattern] = []
    for person in signals.people:
        if person.message_count < MIN_RECURRING_INTERACTIONS or is_noreply(person.email):
            continue
        evidence = Evidence()
        # Scale evidence with interaction volume (capped) so confidence tracks how regular it is.
        for _ in range(min(person.message_count, 12)):
            evidence.add(
                SourceRef("people", person.email, f"interaction with {person.email}",
                          person.last_interaction_at)
            )
        who = person.name or person.email
        patterns.append(
            DerivedPattern(
                pattern_type="recurring_contact",
                subject=person.email,
                description=f"You're in regular contact with {who} "
                f"({person.message_count} interactions).",
                confidence=confidence.score(evidence),
                evidence=evidence,
            )
        )
    return patterns


def all_patterns(signals: Signals) -> list[DerivedPattern]:
    return (
        response_time_patterns(signals)
        + activity_window_pattern(signals)
        + recurring_contact_patterns(signals)
    )
