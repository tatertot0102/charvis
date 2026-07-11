"""Assemble the DashboardState from the WorldModel + existing services (Phase 2F.0).

This is the ONE place the dashboard's facts come from, and it reuses the same engine and services chat
uses — it never calls Gmail/Calendar providers directly and never fabricates. Placeholder sources are
reported as explicitly unavailable. Mode and focus are applied deterministically.
"""
from __future__ import annotations

from datetime import UTC, datetime, time, timedelta
from zoneinfo import ZoneInfo

from app import knowledge
from app.config import get_settings
from app.context import deadlines as deadlines_mod
from app.coordination import waiting as waiting_mod
from app.calendar_actions import store as approvals_store
from app.dashboard import focus as focus_mod
from app.dashboard import layout as layout_mod
from app.dashboard import modes
from app.dashboard.contracts import (
    ApprovalSummary,
    DashboardState,
    EvidenceRef,
    HeroState,
    NotificationItem,
    PriorityItem,
    PriorityState,
    SourceState,
    SourceStatus,
    TodayItem,
    TodayState,
    TopStatus,
    TruthBadge,
    WorkingMemoryItem,
)
from app.dashboard.contracts import EntityWorkspace
from app.integrations.google import calendar as calendar_mod
from app.knowledge.model import Fact, Reality, WorldModel
from app.telemetry import get_logger

log = get_logger(__name__)

_REALITY_BADGE = {
    Reality.VERIFIED: TruthBadge.VERIFIED,
    Reality.LIKELY: TruthBadge.LIKELY,
    Reality.REMEMBERED: TruthBadge.REMEMBERED,
    Reality.INFERRED: TruthBadge.INFERRED,
}
_URGENCY_RANK = {"high": 0, "normal": 1, "low": 2}

# Placeholder sources: named in the registry UI but explicitly not built yet (never fabricated).
_PLACEHOLDER_SOURCES = ["weather", "transit", "news", "todoist", "browser", "device"]
_INTERNAL_SOURCES = ["knowledge", "memory", "commitments", "waiting", "approvals"]


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _badge(reality: Reality) -> TruthBadge:
    return _REALITY_BADGE.get(reality, TruthBadge.INFERRED)


def _evidence(fact: Fact) -> EvidenceRef:
    return EvidenceRef(source=fact.source, provider_object_id=fact.provider_object_id, text=fact.text)


async def build_state(account: str = "default", focus_override: str | None = None) -> DashboardState:
    tz = _tz()
    now = datetime.now(tz)
    settings = get_settings()
    reports = await registry_all(account)
    cal_ok = reports.get("calendar").connected if reports.get("calendar") else False
    gmail_ok = reports.get("gmail").connected if reports.get("gmail") else False

    start = datetime.combine(now.date(), time.min, tzinfo=tz)
    end = now + timedelta(days=settings.deadline_window_days)
    world = await knowledge.query(
        intent="schedule", date_range=(start, end), text="dashboard", account=account
    )

    upcoming = sorted(
        (f for f in world.events if f.when and f.when > now), key=lambda f: f.when
    )
    next_ev = upcoming[0] if upcoming else None
    minutes_to_next = (next_ev.when - now).total_seconds() / 60 if next_ev else None

    dls = await _safe(deadlines_mod.aggregate_deadlines, account, default=[])
    top_dl = _top_deadline(dls)
    waits = await _safe(waiting_mod.list_waiting, account, default=[])
    hi_wait = [w for w in waits if getattr(w, "follow_up_recommended", False)]
    pend = await _safe(approvals_store.list_pending, account, default=[])
    soonest_expiry = _soonest_expiry_minutes(pend, now)

    prefs_layout = await layout_mod.load_layout(account)
    persisted_focus = prefs_layout.focus if prefs_layout else None
    active_focus = focus_override if focus_override is not None else persisted_focus

    signals = modes.ModeSignals(
        minutes_to_next_event=minutes_to_next,
        next_event_is_travel=_event_is_travel(next_ev),
        top_deadline_urgency=top_dl.urgency if top_dl else None,
        approvals_pending=len(pend),
        soonest_approval_expiry_minutes=soonest_expiry,
        calendar_connected=cal_ok,
        gmail_connected=gmail_ok,
        has_conflict=bool(world.conflicts),
        high_priority_waiting=len(hi_wait),
        focus=active_focus,
    )
    mode = modes.select_mode(signals)

    layout = prefs_layout or layout_mod.default_layout(mode, active_focus)
    layout.mode = mode
    layout.focus = active_focus

    hero = _build_hero(next_ev, top_dl, world, now)
    priority = _build_priority(next_ev, top_dl, hi_wait, world, now, active_focus)
    today = _build_today(world, now, tz)
    working = _build_working_memory(active_focus, next_ev, pend, hi_wait, world, now)
    sources = _build_sources(reports)
    notifications = _build_notifications(pend, next_ev, top_dl, reports, world, hi_wait, now)
    approvals = [_approval_summary(p) for p in pend]

    top_status = TopStatus(
        server_time=_iso(now),
        next_event_title=next_ev.data.get("summary") if next_ev else None,
        next_event_countdown_seconds=int((next_ev.when - now).total_seconds()) if next_ev else None,
        brain_healthy=True,
        sources=sources,
    )
    return DashboardState(
        generated_at=_iso(now),
        mode=mode,
        focus=active_focus,
        top_status=top_status,
        hero=hero,
        priority=priority,
        today=today,
        working_memory=working,
        notifications=notifications,
        approvals=approvals,
        layout=layout,
        sources=sources,
    )


# --- section builders ---------------------------------------------------------------------------


def _build_hero(next_ev, top_dl, world: WorldModel, now: datetime) -> HeroState:
    # An imminent event (within 12h) is the strongest hero; else a high-urgency deadline.
    if next_ev and (next_ev.when - now) <= timedelta(hours=12):
        summary = next_ev.data.get("summary") or next_ev.text
        related = [
            _evidence(e) for e in world.emails if e.data.get("on_calendar") == next_ev.provider_object_id
        ][:4]
        context = _matching_commitment(summary, world)
        checklist: list[str] = []
        if related:
            checklist.append(f"Review {len(related)} related email(s)")
        if next_ev.data.get("location"):
            checklist.append(f"Plan travel to {next_ev.data['location']}")
        return HeroState(
            present=True, kind="event", title=summary, when=_iso(next_ev.when),
            countdown_seconds=int((next_ev.when - now).total_seconds()),
            location=next_ev.data.get("location"),
            people=list(next_ev.data.get("attendees") or []),
            context=context, related_emails=related, prep_checklist=checklist,
            badges=[TruthBadge.VERIFIED], evidence=[_evidence(next_ev)],
        )
    if top_dl and top_dl.urgency == "high":
        return HeroState(
            present=True, kind="deadline", title=top_dl.title, when=_iso(top_dl.when),
            countdown_seconds=int((top_dl.when - now).total_seconds()) if top_dl.when else None,
            badges=[TruthBadge.VERIFIED if top_dl.source == "calendar" else TruthBadge.LIKELY],
            evidence=[EvidenceRef(source=top_dl.source, text=f"{top_dl.title} — {top_dl.detail}")],
        )
    return HeroState(present=False, kind="none")


def _build_priority(
    next_ev, top_dl, hi_wait, world: WorldModel, now: datetime, focus: str | None
) -> PriorityState:
    items: list[PriorityItem] = []
    if next_ev and (next_ev.when - now) <= timedelta(hours=48):
        urgent = (next_ev.when - now) <= timedelta(minutes=60)
        items.append(PriorityItem(
            title=next_ev.data.get("summary") or next_ev.text,
            reason="Upcoming calendar event", badge=TruthBadge.VERIFIED,
            confidence=0.95, urgent=urgent, evidence=[_evidence(next_ev)],
        ))
    if top_dl:
        items.append(PriorityItem(
            title=top_dl.title, reason=f"Deadline ({top_dl.urgency})",
            badge=TruthBadge.VERIFIED if top_dl.source == "calendar" else TruthBadge.LIKELY,
            confidence=0.7, urgent=top_dl.urgency == "high",
            evidence=[EvidenceRef(source=top_dl.source, text=top_dl.detail or top_dl.title)],
        ))
    for w in hi_wait[:3]:
        items.append(PriorityItem(
            title=f"Follow up: {w.subject or w.person_email or 'a stalled thread'}",
            reason="You're waiting on a reply", badge=TruthBadge.LIKELY, confidence=0.6,
            evidence=[EvidenceRef(source="waiting", provider_object_id=w.thread_id,
                                  text=w.subject or "")],
        ))
    for c in world.commitments[:2]:
        items.append(PriorityItem(
            title=c.entity or c.text, reason="Active commitment you told me about",
            badge=TruthBadge.REMEMBERED, confidence=c.confidence, context=c.text,
            evidence=[_evidence(c)],
        ))
    ranked = focus_mod.apply_focus(items, focus)
    return PriorityState(top=ranked[0] if ranked else None, secondary=ranked[1:6])


def _build_today(world: WorldModel, now: datetime, tz: ZoneInfo) -> TodayState:
    horizon = now + timedelta(days=1)
    events = [
        TodayItem(title=f.data.get("summary") or f.text, when=_iso(f.when),
                  detail=f.data.get("location"), badge=TruthBadge.VERIFIED,
                  provider_object_id=f.provider_object_id)
        for f in world.events if f.when and now - timedelta(hours=12) <= f.when <= horizon
    ]
    commitments = [
        TodayItem(title=f.entity or f.text, detail=f.text, badge=TruthBadge.REMEMBERED)
        for f in world.commitments[:6]
    ]
    email_events = [
        TodayItem(title=f.data.get("subject") or f.text, when=_iso(f.when), badge=TruthBadge.LIKELY,
                  provider_object_id=f.provider_object_id)
        for f in world.emails if not f.data.get("on_calendar")
    ][:5]
    conflicts = [c.explanation for c in world.conflicts]
    missing = [c.explanation for c in world.conflicts if c.kind == "schedule"]
    return TodayState(events=events, commitments=commitments, email_events=email_events,
                      conflicts=conflicts, missing_calendar=missing)


def _build_working_memory(focus, next_ev, pend, hi_wait, world: WorldModel, now) -> list[WorkingMemoryItem]:
    items: list[WorkingMemoryItem] = []
    if focus:
        items.append(WorkingMemoryItem(label="Current focus", value=focus))
    if next_ev:
        mins = int((next_ev.when - now).total_seconds() / 60)
        items.append(WorkingMemoryItem(
            label="Next event", value=f"{next_ev.data.get('summary') or next_ev.text} (in {mins} min)",
            badge=TruthBadge.VERIFIED,
        ))
    if pend:
        items.append(WorkingMemoryItem(
            label="Pending approval", value=pend[0].summary, badge=TruthBadge.REMEMBERED,
        ))
    if hi_wait:
        w = hi_wait[0]
        items.append(WorkingMemoryItem(
            label="Waiting on", value=w.subject or w.person_email or "a reply", badge=TruthBadge.LIKELY,
        ))
    if world.commitments:
        c = world.commitments[0]
        items.append(WorkingMemoryItem(label="Active commitment", value=c.entity or c.text,
                                       badge=TruthBadge.REMEMBERED))
    return items


def _build_sources(reports: dict) -> list[SourceStatus]:
    out: list[SourceStatus] = []
    for name in ("calendar", "gmail"):
        r = reports.get(name)
        state = SourceState(r.status.value) if r else SourceState.DISCONNECTED
        out.append(SourceStatus(
            name=name, label=name.capitalize(), state=state,
            connected=bool(r and r.connected), healthy=bool(r and r.connected),
            detail=r.detail if r else "", capabilities=["read"],
        ))
    for name in _INTERNAL_SOURCES:
        out.append(SourceStatus(
            name=name, label=name.capitalize(), state=SourceState.CONNECTED,
            connected=True, healthy=True, detail="internal", capabilities=["read"],
        ))
    for name in _PLACEHOLDER_SOURCES:
        out.append(SourceStatus(
            name=name, label=name.capitalize(), state=SourceState.COMING_LATER,
            connected=False, healthy=False, detail="Coming later", placeholder=True,
        ))
    return out


def _build_notifications(pend, next_ev, top_dl, reports, world, hi_wait, now) -> list[NotificationItem]:
    out: list[NotificationItem] = []
    for p in pend:
        exp = _expiry_minutes(p, now)
        sev = "urgent" if (exp is not None and exp <= 10) else "warn"
        out.append(NotificationItem(kind="approval_pending", text=f"Approval needed: {p.summary}",
                                    severity=sev, href="/approvals"))
    if next_ev and (next_ev.when - now) <= timedelta(minutes=60):
        mins = int((next_ev.when - now).total_seconds() / 60)
        out.append(NotificationItem(kind="event_soon",
                                    text=f"{next_ev.data.get('summary') or 'Event'} in {mins} min",
                                    severity="warn"))
    if top_dl and top_dl.urgency == "high":
        out.append(NotificationItem(kind="deadline", text=f"Deadline soon: {top_dl.title}",
                                    severity="warn"))
    for name in ("calendar", "gmail"):
        r = reports.get(name)
        if r and not r.connected:
            out.append(NotificationItem(kind="source_failure",
                                        text=f"{name.capitalize()} is {r.status.value}: {r.detail}",
                                        severity="urgent", href="/sources"))
    for c in world.conflicts:
        out.append(NotificationItem(kind="conflict", text=c.explanation, severity="warn"))
    for w in hi_wait[:3]:
        out.append(NotificationItem(kind="reply_needed",
                                    text=f"No reply on: {w.subject or w.person_email or 'a thread'}",
                                    severity="info"))
    return out


# --- helpers ------------------------------------------------------------------------------------


def _approval_summary(p) -> ApprovalSummary:
    targets = (p.payload or {}).get("targets") or []
    evidence = [EvidenceRef(source="calendar", provider_object_id=t.get("target_event_id"),
                            text=t.get("summary", "")) for t in targets[:5]]
    return ApprovalSummary(
        id=p.id, action_type=p.action_type, summary=p.summary,
        target_event_id=p.target_event_id, confidence=p.confidence, item_count=p.item_count,
        required_phrase=p.required_phrase, expires_at=_iso(p.expires_at), evidence=evidence,
    )


def _top_deadline(dls: list):
    if not dls:
        return None
    return sorted(dls, key=lambda d: (_URGENCY_RANK.get(d.urgency, 3), d.when or datetime.max.replace(tzinfo=UTC)))[0]


def _event_is_travel(fact) -> bool:
    if not fact:
        return False
    return modes.looks_like_travel(fact.data.get("summary"), fact.data.get("location"), fact.text)


def _matching_commitment(summary: str, world: WorldModel) -> str | None:
    low = (summary or "").lower()
    for c in world.commitments:
        ent = (c.entity or "").lower()
        if ent and ent in low:
            return c.text
    return None


def _expiry_minutes(p, now) -> float | None:
    if not p.expires_at:
        return None
    exp = p.expires_at if p.expires_at.tzinfo else p.expires_at.replace(tzinfo=UTC)
    return (exp - now).total_seconds() / 60


def _soonest_expiry_minutes(pend, now) -> float | None:
    mins = [m for m in (_expiry_minutes(p, now) for p in pend) if m is not None]
    return min(mins) if mins else None


async def build_entity_workspace(
    entity_type: str, entity_id: str, account: str = "default"
) -> EntityWorkspace:
    """A per-entity workspace merged from every provider (event/person/project/commitment)."""
    title = entity_id
    if entity_type == "event":
        ev = await _safe(calendar_mod.get_event, entity_id, account, default=None)
        if ev is not None:
            title = ev.summary

    world = await knowledge.query(
        intent="entity", subjects=[title], text=title, account=account
    )
    events = [
        TodayItem(title=f.data.get("summary") or f.text, when=_iso(f.when),
                  detail=f.data.get("location"), badge=TruthBadge.VERIFIED,
                  provider_object_id=f.provider_object_id)
        for f in world.events
    ]
    people = _collect_people(world)
    badges = sorted({_badge(f.reality) for f in world.all_facts()}, key=lambda b: b.value)
    if world.conflicts:
        badges.append(TruthBadge.CONFLICTED)
    summary = (
        f"{len(world.events)} event(s), {len(world.emails)} email(s), "
        f"{len(world.commitments)} commitment(s), {len(world.memory)} memory note(s)."
    )
    return EntityWorkspace(
        entity_type=entity_type, id=entity_id, title=title, summary=summary,
        events=events, emails=[_evidence(f) for f in world.emails[:8]],
        commitments=[f.text for f in world.commitments], memory=[f.text for f in world.memory],
        people=people, waiting=[f.text for f in world.waiting],
        conflicts=[c.explanation for c in world.conflicts],
        evidence=[_evidence(f) for f in world.all_facts()[:12]], badges=badges,
    )


def _collect_people(world: WorldModel) -> list[str]:
    names: list[str] = []
    for f in world.events:
        for a in f.data.get("attendees") or []:
            if a not in names:
                names.append(a)
    for f in world.emails:
        sender = f.data.get("from")
        if sender and sender not in names:
            names.append(sender)
    return names[:10]


async def registry_all(account: str) -> dict:
    from app.sources import registry
    return await _safe(registry.all_reports, account, default={})


async def _safe(fn, *args, default):
    try:
        return await fn(*args)
    except Exception as exc:  # noqa: BLE001 — a failing service degrades gracefully, never 500s.
        log.info("dashboard_service_degraded", fn=getattr(fn, "__name__", str(fn)), error=type(exc).__name__)
        return default
