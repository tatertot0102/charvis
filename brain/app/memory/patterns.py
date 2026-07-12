"""Behavioral pattern detection (Phase 2C.5) — decision-relevant patterns only.

Three deterministic patterns are derived from existing signals:
  - response_time: how fast you typically reply to a given person (sharpens "who's waiting").
  - activity_window: when you tend to do work (informs scheduling / "what should I do next").
  - recurring_contact: who you interact with regularly (feeds priority scoring).
Trivia ("you got 84 LinkedIn emails") is never produced — promotional/no-reply traffic is excluded
upstream, and every pattern must clear a support threshold. Pure; unit-testable with no DB.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime, timedelta
from statistics import median
from zoneinfo import ZoneInfo

from app.integrations.google.classify import is_noreply
from app.knowledge.entities import normalize
from app.memory import confidence
from app.memory.schema import DerivedPattern, Evidence, SourceRef
from app.memory.signals import EventSignal, Signals

MIN_RESPONSES = 2  # need at least this many replies to a person to call it a pattern
MIN_ACTIVITY_EVENTS = 4  # timestamps needed before an activity window is meaningful
ACTIVITY_SHARE = 0.34  # the top window must be at least this fraction of all activity
MIN_RECURRING_INTERACTIONS = 5  # message_count to count someone as a recurring contact
MIN_ROUTINE_OCCURRENCES = 3  # a title must recur at least this often to be a routine
MIN_ROUTINE_WEEKDAYS = 3  # distinct Mon–Fri days before we call something a weekday routine
_WEEKDAY_NAMES = (
    "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday",
)


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


def _local_tz() -> ZoneInfo:
    # Config-only read (no I/O); UTC fallback keeps this unit-testable without a configured tz.
    try:
        from app.config import get_settings

        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _as_local(dt: datetime, tz: ZoneInfo) -> datetime:
    return dt.astimezone(tz) if dt.tzinfo is not None else dt


def _fmt_hour(dt: datetime) -> str:
    return dt.strftime("%-I %p").lstrip("0")


def _time_window(events: list[EventSignal], tz: ZoneInfo) -> str:
    """A human time-of-day window from the occurrences' starts/ends, or '' if unusable."""
    starts = [_as_local(e.start, tz) for e in events if e.start is not None]
    if not starts:
        return ""
    typical_start = sorted(starts, key=lambda d: d.hour)[len(starts) // 2]
    ends = [_as_local(e.end, tz) for e in events if e.end is not None]
    if ends:
        typical_end = sorted(ends, key=lambda d: d.hour)[len(ends) // 2]
        if typical_end.hour != typical_start.hour:
            return f", around {_fmt_hour(typical_start)}–{_fmt_hour(typical_end)}"
    return f", starting around {_fmt_hour(typical_start)}"


def _classify_cadence(events: list[EventSignal], tz: ZoneInfo) -> tuple[str, str] | None:
    """Return (cadence, descriptor) for a title cluster, or None if it isn't a clear routine."""
    dates = sorted({_as_local(e.start, tz).date() for e in events if e.start is not None})
    if len(dates) < MIN_ROUTINE_OCCURRENCES:
        return None
    weekdays = {d.weekday() for d in dates}
    business_days = {w for w in weekdays if w < 5}
    weekday_share = sum(1 for d in dates if d.weekday() < 5) / len(dates)

    # Sparse-but-monthly first: ~one occurrence per month across ≥3 months. Checked before the
    # weekday rule so three monthly meetings that happen to fall on three weekdays aren't mislabelled.
    months = {(d.year, d.month) for d in dates}
    if len(months) >= 3 and len(dates) <= len(months) + 1:
        return ("monthly", "about once a month")
    if len(business_days) >= MIN_ROUTINE_WEEKDAYS and weekday_share >= 0.8:
        return ("weekday", "on most weekdays")
    if len(weekdays) == 1:
        return ("weekly", f"every {_WEEKDAY_NAMES[next(iter(weekdays))]}")
    return None


def routine_patterns(signals: Signals) -> list[DerivedPattern]:
    """Detect weekday / weekly / monthly routines from recurring calendar titles (Phase 2D.4).

    Clusters events by normalized title, classifies each cluster's cadence over the gathered window,
    and describes when it happens — the raw material for answering "what do I do every weekday?".
    Grounded: every routine's evidence is the concrete events that formed it.
    """
    tz = _local_tz()
    clusters: dict[str, list[EventSignal]] = defaultdict(list)
    for event in signals.events:
        if event.start is None:
            continue
        key = normalize(event.summary)
        if not key:
            continue
        clusters[key].append(event)

    out: list[DerivedPattern] = []
    for events in clusters.values():
        if len(events) < MIN_ROUTINE_OCCURRENCES:
            continue
        cadence = _classify_cadence(events, tz)
        if cadence is None:
            continue
        kind, descriptor = cadence
        title = Counter(e.summary for e in events).most_common(1)[0][0]
        window = _time_window(events, tz)
        evidence = Evidence()
        for event in events:
            evidence.add(
                SourceRef("calendar", event.event_id, f"event: {event.summary}", event.start)
            )
        out.append(
            DerivedPattern(
                pattern_type="routine",
                subject=title,
                description=f"“{title}” happens {descriptor}{window}.",
                confidence=confidence.score(evidence),
                evidence=evidence,
            )
        )
    out.sort(key=lambda p: p.confidence, reverse=True)
    return out


def all_patterns(signals: Signals) -> list[DerivedPattern]:
    return (
        response_time_patterns(signals)
        + activity_window_pattern(signals)
        + recurring_contact_patterns(signals)
        + routine_patterns(signals)
    )
