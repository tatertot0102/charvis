"""Dashboard HTTP contract (Phase 2F.0).

One aggregated state endpoint so the frontend never has to stitch 15 endpoints together, plus layout
persistence and per-entity workspaces. Everything reuses the WorldModel + existing services; no
business logic is duplicated here, and no factual content originates in the frontend.

- GET  /dashboard/state              → the whole DashboardState (mode, hero, priority, today, …)
- GET  /dashboard/layout             → persisted layout (or the default)
- POST /dashboard/layout             → apply ONE validated LayoutCommand; 422 if off-schema
- GET  /dashboard/entity/{type}/{id} → merged per-entity workspace
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.dashboard import aggregate, layout as layout_mod
from app.dashboard.contracts import (
    DashboardMode,
    DashboardState,
    EntityWorkspace,
    LayoutCommand,
    LayoutState,
)
from app.deps import require_token

router = APIRouter(tags=["dashboard"])


@router.get("/dashboard/state", response_model=DashboardState)
async def dashboard_state(
    focus: str | None = None, _: None = Depends(require_token)
) -> DashboardState:
    """The full, deterministically-assembled dashboard state. `focus` overrides the saved focus."""
    return await aggregate.build_state(account="default", focus_override=focus)


@router.get("/dashboard/layout", response_model=LayoutState)
async def get_layout(_: None = Depends(require_token)) -> LayoutState:
    return await layout_mod.load_layout("default") or layout_mod.default_layout(DashboardMode.IDLE)


@router.post("/dashboard/layout", response_model=LayoutState)
async def post_layout(cmd: LayoutCommand, _: None = Depends(require_token)) -> LayoutState:
    """Apply a single validated layout command. Off-schema commands are rejected (current kept)."""
    current = await layout_mod.load_layout("default") or layout_mod.default_layout(DashboardMode.IDLE)
    updated = layout_mod.validate_command(current, cmd)
    if updated is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid or unsafe layout command — ignored.",
        )
    await layout_mod.save_layout(updated, "default")
    return updated


@router.get("/dashboard/entity/{entity_type}/{entity_id:path}", response_model=EntityWorkspace)
async def entity_workspace(
    entity_type: str, entity_id: str, _: None = Depends(require_token)
) -> EntityWorkspace:
    if entity_type not in {"event", "person", "project", "commitment", "entity"}:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="unknown entity type")
    return await aggregate.build_entity_workspace(entity_type, entity_id, "default")
