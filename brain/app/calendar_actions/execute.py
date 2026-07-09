"""Replay a CONFIRMED pending action through the write connector (Phase 2D).

This is the ONLY code path that mutates the calendar, and it runs only for an action the caller has
already verified is pending, unexpired, and confirmed. It performs no policy checks of its own beyond
parsing its payload — the gate lives in app.calendar_actions.service. Returns (ok, message); the
caller records status and replies.
"""
from __future__ import annotations

from datetime import datetime

from app.calendar_actions.schema import ActionType
from app.db.models import PendingCalendarAction
from app.integrations.google import calendar, calendar_write
from app.telemetry import get_logger

log = get_logger(__name__)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


class ExecutionError(RuntimeError):
    """A calendar write failed after confirmation — carries a user-facing reason."""


async def execute_action(row: PendingCalendarAction) -> str:
    """Perform the confirmed write. Returns a short success message; raises ExecutionError on failure."""
    account = row.account
    payload = row.payload or {}
    try:
        if row.action_type == ActionType.CREATE.value:
            created = await calendar_write.create_event(
                summary=payload["summary"],
                start=_dt(payload["start"]),
                end=_dt(payload["end"]),
                location=payload.get("location"),
                account=account,
            )
            return f'Created “{payload["summary"]}” ✓'.strip() + _link(created)

        if row.action_type == ActionType.UPDATE.value:
            await calendar_write.update_event(
                row.target_event_id,
                start=_dt(payload.get("start")),
                end=_dt(payload.get("end")),
                account=account,
            )
            return f'Moved “{payload.get("summary", "event")}” ✓'

        if row.action_type == ActionType.DELETE.value:
            await calendar_write.delete_event(row.target_event_id, account=account)
            return f'Cancelled “{payload.get("summary", "event")}” ✓'

        raise ExecutionError(f"Unknown action type: {row.action_type}")
    except calendar_write.WriteScopeError as exc:
        log.warning("calendar_write_scope_missing", action_id=row.id)
        raise ExecutionError(
            "I don't have calendar write permission yet — re-run /connect_google to grant it, "
            "then confirm again."
        ) from exc
    except calendar.NotConnectedError as exc:
        raise ExecutionError("Google Calendar isn't connected.") from exc
    except KeyError as exc:  # malformed payload — should never happen, but never crash the flow.
        log.error("calendar_action_payload_invalid", action_id=row.id, missing=str(exc))
        raise ExecutionError("That proposal was malformed — ask me to draft it again.") from exc


def _link(created: dict) -> str:
    link = created.get("htmlLink")
    return f"\n{link}" if link else ""
