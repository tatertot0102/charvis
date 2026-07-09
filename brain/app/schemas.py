"""Pydantic request/response schemas for the HTTP API."""
from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    session_id: str = Field(default="default", max_length=128)


class ChatResponse(BaseModel):
    reply: str
    conversation_id: int


class CaptureRequest(BaseModel):
    text: str = Field(min_length=1, max_length=8000)


class CaptureResponse(BaseModel):
    id: int
    status: str = "captured"


# --- Phase 2A: Google Calendar (read-only) ---


class GoogleConnectResponse(BaseModel):
    """The consent URL the operator opens in a browser to authorize read-only Calendar access."""

    auth_url: str


class CalendarEventOut(BaseModel):
    summary: str
    start: str  # ISO 8601
    end: str  # ISO 8601
    all_day: bool
    location: str | None = None


class TodayCalendarResponse(BaseModel):
    connected: bool
    timezone: str
    events: list[CalendarEventOut] = Field(default_factory=list)
    detail: str | None = None  # e.g. how to connect when connected is False


# --- Phase 2B: Gmail (read-only) ---


class EmailMessageOut(BaseModel):
    gmail_id: str
    thread_id: str
    from_email: str
    from_name: str | None = None
    to_emails: list[str] = Field(default_factory=list)
    subject: str
    snippet: str
    received_at: str | None = None  # ISO 8601
    is_unread: bool
    direction: str  # inbound | outbound
    importance: str  # high | normal | low
    urgency: str  # high | normal | low
    requires_response: bool
    is_promotional: bool
    is_calendar_related: bool
    is_deadline_related: bool
    is_fyi: bool


class GmailListResponse(BaseModel):
    connected: bool
    count: int = 0
    messages: list[EmailMessageOut] = Field(default_factory=list)
    detail: str | None = None


class GmailThreadResponse(BaseModel):
    connected: bool
    thread_id: str
    messages: list[EmailMessageOut] = Field(default_factory=list)
    detail: str | None = None


class WaitingItemOut(BaseModel):
    kind: str  # waiting_on_them | waiting_on_me
    thread_id: str
    person_email: str | None = None
    subject: str
    last_message_at: str | None = None  # ISO 8601
    last_message_direction: str
    follow_up_recommended: bool
    days_waiting: int


class WaitingResponse(BaseModel):
    connected: bool
    waiting_on_them: list[WaitingItemOut] = Field(default_factory=list)
    waiting_on_me: list[WaitingItemOut] = Field(default_factory=list)
    detail: str | None = None


# --- Phase 2C: unified intelligence / state ---


class StateTodayResponse(BaseModel):
    connected: bool
    timezone: str
    events: list[CalendarEventOut] = Field(default_factory=list)
    waiting_on_me_count: int = 0
    waiting_on_them_count: int = 0
    summary: str = ""  # human-readable one-line overview of the day
    detail: str | None = None


class DeadlineOut(BaseModel):
    source: str  # calendar | email
    title: str
    when: str | None = None  # ISO 8601, or null for undated email deadlines
    detail: str
    urgency: str  # high | normal | low


class DeadlinesResponse(BaseModel):
    connected: bool
    deadlines: list[DeadlineOut] = Field(default_factory=list)
    detail: str | None = None


class NextActionResponse(BaseModel):
    connected: bool
    recommendation: str = ""
    detail: str | None = None


class RelatedEmailOut(BaseModel):
    gmail_id: str
    thread_id: str
    from_email: str
    from_name: str | None = None
    subject: str
    snippet: str
    received_at: str | None = None
    is_unread: bool
    reason: str  # why it was linked to the event


class EventBriefingResponse(BaseModel):
    connected: bool
    has_event: bool
    event: CalendarEventOut | None = None
    briefing: str = ""  # synthesized natural-language brief
    related_emails: list[RelatedEmailOut] = Field(default_factory=list)
    waiting_on_me_count: int = 0
    detail: str | None = None


# --- Phase 2C.5: memory (evidence-backed conclusions about "me") -------------


class ContextTagOut(BaseModel):
    name: str
    confidence: float


class ConclusionOut(BaseModel):
    kind: str  # project | person | preference | relationship
    subject: str
    statement: str
    confidence: float
    evidence: dict = Field(default_factory=dict)  # {by_source: {...}, records: [...]}
    source_list: list[str] = Field(default_factory=list)
    contexts: list[ContextTagOut] = Field(default_factory=list)
    first_seen: str | None = None
    last_updated: str | None = None


class ConclusionsResponse(BaseModel):
    count: int = 0
    conclusions: list[ConclusionOut] = Field(default_factory=list)


class PatternOut(BaseModel):
    pattern_type: str
    subject: str
    description: str
    confidence: float
    evidence: dict = Field(default_factory=dict)
    source_list: list[str] = Field(default_factory=list)
    first_seen: str | None = None
    last_updated: str | None = None


class PatternsResponse(BaseModel):
    count: int = 0
    patterns: list[PatternOut] = Field(default_factory=list)


class CommitmentOut(BaseModel):
    direction: str  # owed_by_me | owed_to_me | deadline
    description: str
    counterparty: str | None = None
    due_at: str | None = None
    confidence: float
    evidence: dict = Field(default_factory=dict)
    source_list: list[str] = Field(default_factory=list)
    first_seen: str | None = None
    last_updated: str | None = None


class CommitmentsResponse(BaseModel):
    count: int = 0
    commitments: list[CommitmentOut] = Field(default_factory=list)


class ConsolidateResponse(BaseModel):
    conclusions: int
    patterns: int
    commitments: int
    context_tags: int


# --- Phase 2D: calendar actions with confirmation (approval queue) ------------


class PendingActionOut(BaseModel):
    id: int
    account: str
    action_type: str  # create | update | delete
    status: str  # pending | executed | cancelled | expired | superseded | failed
    summary: str  # the exact proposed change shown to the user
    target_event_id: str | None = None
    proposed_at: str | None = None  # ISO 8601
    expires_at: str | None = None  # ISO 8601
    resolved_at: str | None = None  # ISO 8601
    result: str | None = None


class ApprovalsResponse(BaseModel):
    count: int = 0
    actions: list[PendingActionOut] = Field(default_factory=list)


class ApprovalDecisionResponse(BaseModel):
    id: int
    status: str  # the action's status after the decision
    message: str  # human-readable result of confirm/cancel
