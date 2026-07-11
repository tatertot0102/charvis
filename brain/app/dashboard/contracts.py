"""Strict typed contracts crossing the dashboard frontend/backend boundary (Phase 2F.0).

No loose dicts: every dashboard payload is one of these Pydantic models with explicit enums. The
frontend mirrors these as TypeScript types. Truth badges are mandatory on factual items so nothing is
ever shown without its provenance.
"""
from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field


class DashboardMode(str, Enum):
    IDLE = "idle"
    PRE_EVENT = "pre_event"
    TRAVEL = "travel"
    DEEP_WORK = "deep_work"
    DEADLINE = "deadline"
    CRISIS = "crisis"


class TruthBadge(str, Enum):
    VERIFIED = "verified"      # provider-backed (Google)
    REMEMBERED = "remembered"  # user told Jarvis
    LIKELY = "likely"          # email-derived, not yet confirmed
    INFERRED = "inferred"      # detected pattern
    CONFLICTED = "conflicted"  # sources disagree
    STALE = "stale"            # last-known, possibly out of date


class SectionId(str, Enum):
    HERO = "hero"
    PRIORITY = "priority"
    TODAY = "today"
    WORKING_MEMORY = "working_memory"
    NOTIFICATIONS = "notifications"
    APPROVALS = "approvals"


class SourceState(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    UNAVAILABLE = "unavailable"      # server misconfig
    PERMISSION_MISSING = "permission_missing"
    TOKEN_EXPIRED = "token_expired"
    REQUEST_FAILED = "request_failed"
    COMING_LATER = "coming_later"    # placeholder source not built yet


class SourceStatus(BaseModel):
    name: str
    label: str
    state: SourceState
    connected: bool
    healthy: bool
    detail: str = ""
    capabilities: list[str] = Field(default_factory=list)
    placeholder: bool = False


class EvidenceRef(BaseModel):
    source: str
    provider_object_id: str | None = None
    text: str


class HeroState(BaseModel):
    present: bool = False
    kind: str = ""                  # event | deadline | none
    title: str = ""
    when: str | None = None         # ISO
    countdown_seconds: int | None = None
    location: str | None = None
    people: list[str] = Field(default_factory=list)
    context: str | None = None      # commitment/project context
    related_emails: list[EvidenceRef] = Field(default_factory=list)
    prep_checklist: list[str] = Field(default_factory=list)
    badges: list[TruthBadge] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PriorityItem(BaseModel):
    title: str
    reason: str = ""
    badge: TruthBadge = TruthBadge.INFERRED
    confidence: float = 0.0
    urgent: bool = False
    context: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class PriorityState(BaseModel):
    top: PriorityItem | None = None
    secondary: list[PriorityItem] = Field(default_factory=list)


class TodayItem(BaseModel):
    title: str
    when: str | None = None
    detail: str | None = None
    badge: TruthBadge
    provider_object_id: str | None = None


class TodayState(BaseModel):
    events: list[TodayItem] = Field(default_factory=list)          # verified calendar
    commitments: list[TodayItem] = Field(default_factory=list)     # remembered
    email_events: list[TodayItem] = Field(default_factory=list)    # likely
    conflicts: list[str] = Field(default_factory=list)
    missing_calendar: list[str] = Field(default_factory=list)


class WorkingMemoryItem(BaseModel):
    label: str
    value: str
    badge: TruthBadge | None = None
    done: bool = False


class NotificationItem(BaseModel):
    kind: str          # reply_needed | approval_pending | event_soon | deadline | source_failure | conflict | missing_calendar
    text: str
    severity: str = "info"   # info | warn | urgent
    href: str | None = None


class ApprovalSummary(BaseModel):
    id: int
    action_type: str
    summary: str
    target_event_id: str | None = None
    confidence: float = 0.0
    item_count: int = 1
    required_phrase: str = "CONFIRM"
    expires_at: str | None = None
    evidence: list[EvidenceRef] = Field(default_factory=list)


class DashboardSection(BaseModel):
    id: SectionId
    visible: bool = True
    collapsed: bool = False
    size: str = "md"   # sm | md | lg
    order: int = 0


class LayoutState(BaseModel):
    mode: DashboardMode = DashboardMode.IDLE
    sections: list[DashboardSection] = Field(default_factory=list)
    focus: str | None = None
    last_workspace: str | None = None


class TopStatus(BaseModel):
    server_time: str
    next_event_title: str | None = None
    next_event_countdown_seconds: int | None = None
    brain_healthy: bool = True
    sources: list[SourceStatus] = Field(default_factory=list)


class DashboardState(BaseModel):
    generated_at: str
    mode: DashboardMode
    focus: str | None = None
    top_status: TopStatus
    hero: HeroState
    priority: PriorityState
    today: TodayState
    working_memory: list[WorkingMemoryItem] = Field(default_factory=list)
    notifications: list[NotificationItem] = Field(default_factory=list)
    approvals: list[ApprovalSummary] = Field(default_factory=list)
    layout: LayoutState
    sources: list[SourceStatus] = Field(default_factory=list)


class EntityWorkspace(BaseModel):
    entity_type: str
    id: str
    title: str
    summary: str
    events: list[TodayItem] = Field(default_factory=list)
    emails: list[EvidenceRef] = Field(default_factory=list)
    commitments: list[str] = Field(default_factory=list)
    memory: list[str] = Field(default_factory=list)
    people: list[str] = Field(default_factory=list)
    waiting: list[str] = Field(default_factory=list)
    conflicts: list[str] = Field(default_factory=list)
    evidence: list[EvidenceRef] = Field(default_factory=list)
    badges: list[TruthBadge] = Field(default_factory=list)


# --- validated command schemas (the ONLY way the model may influence the UI) ------------------


class LayoutCommand(BaseModel):
    """A single validated layout mutation the assistant may propose. Anything off-schema is ignored."""

    action: str  # reorder | show | hide | collapse | expand | resize | set_focus | open_workspace
    section: SectionId | None = None
    order: list[SectionId] | None = None
    size: str | None = None
    focus: str | None = None
    workspace: str | None = None


class NavigationCommand(BaseModel):
    route: str | None = None
    selected_entity: str | None = None
