"""Approval-queue endpoints (Phase 2D) — the HTTP face of the calendar-write confirmation gate.

- GET  /approvals             → list pending calendar actions (the drafts awaiting a decision).
- POST /approvals/{id}/confirm → execute exactly that action, if still pending and unexpired.
- POST /approvals/{id}/cancel  → drop it without executing.

Confirm is the ONLY endpoint that can cause a calendar write, and only through the same gated path
the Telegram "CONFIRM" reply uses (app.calendar_actions.service). A missing/decided action yields a
clear message, never a silent write.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status

from app.calendar_actions import service, store
from app.db.models import PendingCalendarAction
from app.deps import require_token
from app.schemas import ApprovalDecisionResponse, ApprovalsResponse, PendingActionOut

router = APIRouter(tags=["approvals"])


def _iso(dt: datetime | None) -> str | None:
    return dt.isoformat() if dt else None


def _out(row: PendingCalendarAction) -> PendingActionOut:
    return PendingActionOut(
        id=row.id,
        account=row.account,
        action_type=row.action_type,
        status=row.status,
        summary=row.summary,
        target_event_id=row.target_event_id,
        proposed_at=_iso(row.proposed_at),
        expires_at=_iso(row.expires_at),
        resolved_at=_iso(row.resolved_at),
        result=row.result,
    )


@router.get("/approvals", response_model=ApprovalsResponse)
async def list_approvals(_: None = Depends(require_token)) -> ApprovalsResponse:
    """Pending calendar actions awaiting confirmation, newest first."""
    rows = await store.list_pending()
    return ApprovalsResponse(count=len(rows), actions=[_out(r) for r in rows])


@router.post("/approvals/{action_id}/confirm", response_model=ApprovalDecisionResponse)
async def confirm_approval(
    action_id: int, _: None = Depends(require_token)
) -> ApprovalDecisionResponse:
    """Confirm and execute a specific pending action (the only endpoint that can write)."""
    found, message = await service.confirm_by_id(action_id, account="default")
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    row = await store.get(action_id)
    return ApprovalDecisionResponse(id=action_id, status=row.status if row else "unknown", message=message)


@router.post("/approvals/{action_id}/cancel", response_model=ApprovalDecisionResponse)
async def cancel_approval(
    action_id: int, _: None = Depends(require_token)
) -> ApprovalDecisionResponse:
    """Cancel a specific pending action without executing it."""
    found, message = await service.cancel_by_id(action_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=message)
    row = await store.get(action_id)
    return ApprovalDecisionResponse(id=action_id, status=row.status if row else "unknown", message=message)
