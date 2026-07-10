"""Chat glue for Phase 2D calendar actions — shared by Telegram and /chat.

Thin, never-raises wrappers around app.calendar_actions.service plus free-time formatting. All
proposal/confirmation text is produced downstream; this layer only routes and formats reads.
"""
from __future__ import annotations

from app.calendar_actions import conflicts, service
from app.integrations.google import calendar
from app.security.crypto import EncryptionUnavailableError
from app.telemetry import get_logger

log = get_logger(__name__)

_NOT_CONNECTED = "I'm not connected to your Google Calendar yet. Send /connect_google first."
_NO_KEY = "I can't read your calendar yet — the encryption key isn't configured on the server."
_ERROR = "Sorry — I couldn't check your calendar just now. Try again in a moment."


async def handle_confirm(account: str = "default", phrase: str = "CONFIRM") -> str:
    return await service.confirm_latest(account, phrase=phrase)


async def handle_cancel(account: str = "default") -> str:
    return await service.cancel_latest(account)


async def handle_request(
    text: str, *, channel: str, external_id: str | None, account: str = "default"
) -> str | None:
    """Draft a proposal if `text` is a calendar action; None if it isn't ours to handle."""
    return await service.request(text, channel=channel, external_id=external_id, account=account)


def _fmt_slot(slot: conflicts.FreeSlot) -> str:
    start = slot.start.strftime("%-I:%M %p").lstrip("0")
    end = slot.end.strftime("%-I:%M %p").lstrip("0")
    return f"• {start} – {end}"


async def handle_free_time(day_offset: int = 0, account: str = "default") -> str:
    """Format open slots in the workday. Never raises."""
    try:
        slots = await conflicts.free_time(day_offset=day_offset, account=account)
    except calendar.NotConnectedError:
        return _NOT_CONNECTED
    except EncryptionUnavailableError:
        return _NO_KEY
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("free_time_failed", error=str(exc), error_type=type(exc).__name__)
        return _ERROR
    if not slots:
        return "Your workday looks fully booked — no open slots."
    when = "today" if day_offset == 0 else f"in {day_offset} day(s)"
    return "\n".join([f"Open time {when}:", *[_fmt_slot(s) for s in slots]])
