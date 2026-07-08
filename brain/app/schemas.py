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
