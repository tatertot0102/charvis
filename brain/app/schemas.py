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
