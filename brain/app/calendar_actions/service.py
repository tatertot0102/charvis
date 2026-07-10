"""The calendar-actions front door (Phase 2D) — request, confirm, cancel.

Enforces THE HARD RULE in one place: a write executes only via _confirm_row, and only when the row is
pending and unexpired. `request()` drafts (never writes); `confirm_latest()` is what "CONFIRM" hits;
the endpoints use the by-id variants. Everything returns user-facing text.
"""
from __future__ import annotations

from app.calendar_actions import execute, parse, propose, store
from app.calendar_actions.schema import ActionStatus
from app.calendar_state import snapshots
from app.db.models import PendingCalendarAction
from app.security.crypto import EncryptionUnavailableError
from app.telemetry import get_logger

log = get_logger(__name__)

_NO_KEY = "I can't act on your calendar yet — the encryption key isn't configured on the server."
_ERROR = "Sorry — I couldn't work that out just now. Try again in a moment."
_NOTHING = "Nothing's pending confirmation right now."


async def request(
    text: str, *, channel: str = "telegram", external_id: str | None = None, account: str = "default"
) -> str | None:
    """Parse a message; draft a proposal if it's a calendar action. None → not ours to handle.

    Read-only end to end: at most this writes a *pending* row. No calendar write happens here.
    """
    parsed = parse.detect(text)
    if parsed is None:
        return None
    try:
        outcome = await propose.build(
            parsed, channel=channel, external_id=external_id, account=account
        )
    except EncryptionUnavailableError:
        return _NO_KEY
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("calendar_action_propose_failed", error=str(exc), error_type=type(exc).__name__)
        return _ERROR
    return outcome.text


def _phrase_mismatch_text(row: PendingCalendarAction, phrase: str) -> str:
    """Explain why the reply didn't confirm this action — without executing it."""
    required = row.required_phrase or "CONFIRM"
    if required != "CONFIRM":
        # A bulk/destructive action needs the stronger phrase; a plain CONFIRM must NOT fire it.
        return (
            f"That would affect {row.item_count} event{'s' if row.item_count != 1 else ''}. "
            f"To be safe, reply exactly “{required}” to proceed, or “cancel” to drop it."
        )
    return f"Reply exactly “{required}” to apply this, or “cancel” to drop it."


async def _confirm_row(row: PendingCalendarAction, phrase: str) -> str:
    """The single gate: execute a row only if pending, unexpired, and confirmed with its phrase."""
    if row.status != ActionStatus.PENDING.value:
        return f"That action was already {row.status}. Ask me to draft a fresh one if you need it."
    if store.is_expired(row):
        await store.set_status(row.id, ActionStatus.EXPIRED, result="expired before confirmation")
        return "That proposal expired before you confirmed it — ask me to draft it again."
    if phrase != (row.required_phrase or "CONFIRM"):
        # Wrong/weaker confirmation → never execute. Leave it pending so the user can retry.
        return _phrase_mismatch_text(row, phrase)
    try:
        message = await execute.execute_action(row)
    except execute.ExecutionError as exc:
        await store.set_status(row.id, ActionStatus.FAILED, result=str(exc))
        return str(exc)
    await store.set_status(row.id, ActionStatus.EXECUTED, result=message)
    log.info("calendar_action_executed", action_id=row.id, kind=row.action_type, phrase=phrase)
    await _refresh_snapshots(row.account)
    return message


async def _refresh_snapshots(account: str) -> None:
    """After a confirmed write, re-mirror reality so the next week/schedule answer isn't stale.

    Best-effort: a failed refresh must never turn a successful write into an error to the user.
    """
    try:
        await snapshots.rebuild(account)
    except Exception as exc:  # noqa: BLE001 — the write already succeeded; just log a stale cache.
        log.warning("snapshot_refresh_failed", account=account, error=str(exc))


async def confirm_latest(account: str = "default", phrase: str = "CONFIRM") -> str:
    """Confirm the most recent pending action. `phrase` is the exact text the user sent.

    A bulk delete requires "CONFIRM DELETE"; a plain "CONFIRM" will not fire it (Phase 2D.1).
    """
    row = await store.latest_pending(account)
    if row is None:
        return _NOTHING
    # Only the latest may execute; retire any older stragglers so they can't fire later.
    await store.supersede_pending(account, except_id=row.id)
    return await _confirm_row(row, phrase)


async def cancel_latest(account: str = "default") -> str:
    """Cancel the most recent pending action without executing it."""
    row = await store.latest_pending(account)
    if row is None:
        return _NOTHING
    await store.set_status(row.id, ActionStatus.CANCELLED, result="cancelled by user")
    return f"Okay — cancelled that pending change ({row.action_type})."


async def confirm_by_id(
    action_id: int, account: str | None = None, phrase: str | None = None
) -> tuple[bool, str]:
    """Confirm a specific pending action (endpoint path). Returns (found, message).

    The endpoint is explicit intent, so it confirms with the action's own required phrase by default
    (a bulk delete still executes), but the confirmation gate — pending + unexpired + valid ids —
    is unchanged.
    """
    row = await store.get(action_id)
    if row is None:
        return False, "No such pending action."
    if account is not None:
        await store.supersede_pending(row.account, except_id=row.id)
    return True, await _confirm_row(row, phrase or (row.required_phrase or "CONFIRM"))


async def cancel_by_id(action_id: int) -> tuple[bool, str]:
    """Cancel a specific pending action (endpoint path). Returns (found, message)."""
    row = await store.get(action_id)
    if row is None:
        return False, "No such pending action."
    if row.status != ActionStatus.PENDING.value:
        return True, f"That action was already {row.status}."
    await store.set_status(action_id, ActionStatus.CANCELLED, result="cancelled via endpoint")
    return True, "Cancelled."
