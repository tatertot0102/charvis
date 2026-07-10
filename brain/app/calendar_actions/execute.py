"""Replay a CONFIRMED pending action through the write connector (Phase 2D / 2D.1).

The ONLY code path that mutates the calendar. It runs only for an action the gate has already
verified is pending, unexpired, and confirmed with the correct phrase. Its own job is narrow but
critical for anti-hallucination: before mutating, it re-validates every target id against Google
(calendar.get_event) so unknown / fabricated / stale / deleted ids can never be written — and the
connector itself raises RejectedEventError on a 404/410 as a second line of defense.

Returns a short success message; raises ExecutionError on failure. Bulk actions report how many
events were changed, skipped (already gone), or failed.
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


async def _validate_id(event_id: str | None, account: str) -> bool:
    """True only if `event_id` is a real, live provider event. Never trusts a stored id blindly."""
    if not event_id:
        return False
    return (await calendar.get_event(event_id, account=account)) is not None


async def execute_action(row: PendingCalendarAction) -> str:
    """Perform the confirmed write. Returns a success message; raises ExecutionError on failure."""
    payload = row.payload or {}
    if payload.get("bulk"):
        return await _execute_bulk(row)
    try:
        if row.action_type == ActionType.CREATE.value:
            return await _execute_create(row.account, payload)
        # update / delete both target an existing id — validate it against the provider first.
        if not await _validate_id(row.target_event_id, row.account):
            raise ExecutionError(
                "That event no longer exists in your calendar (it may have been moved or deleted). "
                "I won't touch anything — ask me to draft it again."
            )
        if row.action_type == ActionType.UPDATE.value:
            await calendar_write.update_event(
                row.target_event_id,
                start=_dt(payload.get("start")),
                end=_dt(payload.get("end")),
                account=row.account,
            )
            return f'Moved “{payload.get("summary", "event")}” ✓'
        if row.action_type == ActionType.DELETE.value:
            await calendar_write.delete_event(row.target_event_id, account=row.account)
            return f'Cancelled “{payload.get("summary", "event")}” ✓'
        raise ExecutionError(f"Unknown action type: {row.action_type}")
    except calendar_write.RejectedEventError as exc:
        raise ExecutionError(
            "That event id was rejected by Google (unknown or already deleted) — nothing changed."
        ) from exc
    except calendar_write.WriteScopeError as exc:
        raise _scope_error() from exc
    except calendar.NotConnectedError as exc:
        raise ExecutionError("Google Calendar isn't connected.") from exc
    except KeyError as exc:
        log.error("calendar_action_payload_invalid", action_id=row.id, missing=str(exc))
        raise ExecutionError("That proposal was malformed — ask me to draft it again.") from exc


async def _execute_create(account: str, payload: dict) -> str:
    try:
        created = await calendar_write.create_event(
            summary=payload["summary"],
            start=_dt(payload["start"]),
            end=_dt(payload["end"]),
            location=payload.get("location"),
            recurrence=payload.get("recurrence"),
            account=account,
        )
    except calendar_write.WriteScopeError as exc:
        raise _scope_error() from exc
    link = created.get("htmlLink")
    return f'Created “{payload["summary"]}” ✓' + (f"\n{link}" if link else "")


async def _execute_bulk(row: PendingCalendarAction) -> str:
    """Execute a bulk delete/move over provider-validated targets only."""
    account = row.account
    is_move = row.action_type == ActionType.UPDATE.value
    verb_past = "Moved" if is_move else "Cancelled"
    targets = (row.payload or {}).get("targets", [])

    done = 0
    skipped = 0  # target no longer exists (validated away — never a fabricated write)
    failed = 0
    for target in targets:
        event_id = target.get("target_event_id")
        try:
            if not await _validate_id(event_id, account):
                skipped += 1
                continue
            if is_move:
                await calendar_write.update_event(
                    event_id,
                    start=_dt(target.get("new_start")),
                    end=_dt(target.get("new_end")),
                    account=account,
                )
            else:
                await calendar_write.delete_event(event_id, account=account)
            done += 1
        except calendar_write.RejectedEventError:
            skipped += 1
        except calendar_write.WriteScopeError as exc:
            raise _scope_error() from exc
        except Exception as exc:  # noqa: BLE001 — one bad event must not abort the batch.
            log.error("bulk_calendar_item_failed", action_id=row.id, event_id=event_id, error=str(exc))
            failed += 1

    parts = [f"{verb_past} {done} event{'s' if done != 1 else ''} ✓"]
    if skipped:
        parts.append(f"{skipped} already gone (skipped)")
    if failed:
        parts.append(f"{failed} failed")
    return "; ".join(parts)


def _scope_error() -> "ExecutionError":
    return ExecutionError(
        "I don't have calendar write permission yet — re-run /connect_google to grant it, "
        "then confirm again."
    )
