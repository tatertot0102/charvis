"""/calendar/today — read-only view of today's Google Calendar events (Phase 2A).

Returns 200 with connected=False (not an error) when Google isn't authorized yet, so the dashboard
and callers can render a "connect me" state without special-casing an error code.
"""
from fastapi import APIRouter, Depends

from app.config import get_settings
from app.deps import require_token
from app.integrations.google import calendar
from app.schemas import CalendarEventOut, TodayCalendarResponse

router = APIRouter(tags=["calendar"])

_NOT_CONNECTED_DETAIL = (
    "Google Calendar is not connected. GET /integrations/google/connect to authorize."
)


@router.get("/calendar/today", response_model=TodayCalendarResponse)
async def calendar_today(_: None = Depends(require_token)) -> TodayCalendarResponse:
    timezone = get_settings().tz
    try:
        events = await calendar.list_todays_events()
    except calendar.NotConnectedError:
        return TodayCalendarResponse(
            connected=False, timezone=timezone, events=[], detail=_NOT_CONNECTED_DETAIL
        )
    return TodayCalendarResponse(
        connected=True,
        timezone=timezone,
        events=[
            CalendarEventOut(
                summary=event.summary,
                start=event.start.isoformat(),
                end=event.end.isoformat(),
                all_day=event.all_day,
                location=event.location,
            )
            for event in events
        ],
    )
