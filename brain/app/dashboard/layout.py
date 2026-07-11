"""Deterministic default layouts per mode + validated layout commands + persistence (Phase 2F.0).

The layout is a strict schema. Default layouts are fixed per mode. The assistant may only mutate the
layout through validated LayoutCommands — anything off-schema is rejected and the current layout is
kept. No JSX or model-generated UI is ever stored; only section order/visibility/size + focus.
"""
from __future__ import annotations

from sqlalchemy import select

from app.dashboard.contracts import (
    DashboardMode,
    DashboardSection,
    LayoutCommand,
    LayoutState,
    SectionId,
)
from app.db.models import DashboardPref
from app.db.session import get_session

_ALL = [
    SectionId.HERO, SectionId.PRIORITY, SectionId.TODAY,
    SectionId.WORKING_MEMORY, SectionId.NOTIFICATIONS, SectionId.APPROVALS,
]
_VALID_SIZES = {"sm", "md", "lg"}

# Per-mode emphasis: {section: (size, collapsed)}; a section absent from the map keeps default md/open.
_MODE_EMPHASIS: dict[DashboardMode, dict[SectionId, tuple[str, bool]]] = {
    DashboardMode.IDLE: {
        SectionId.PRIORITY: ("lg", False), SectionId.TODAY: ("lg", False),
        SectionId.HERO: ("md", False),
    },
    DashboardMode.PRE_EVENT: {
        SectionId.HERO: ("lg", False), SectionId.TODAY: ("sm", False),
        SectionId.WORKING_MEMORY: ("sm", False), SectionId.APPROVALS: ("md", False),
    },
    DashboardMode.TRAVEL: {
        SectionId.HERO: ("lg", False), SectionId.TODAY: ("md", False),
        SectionId.WORKING_MEMORY: ("sm", False), SectionId.NOTIFICATIONS: ("sm", False),
    },
    DashboardMode.DEEP_WORK: {
        SectionId.PRIORITY: ("lg", False), SectionId.HERO: ("sm", False),
        SectionId.TODAY: ("sm", False), SectionId.NOTIFICATIONS: ("sm", True),
    },
    DashboardMode.DEADLINE: {
        SectionId.PRIORITY: ("lg", False), SectionId.TODAY: ("md", False),
        SectionId.HERO: ("md", False), SectionId.NOTIFICATIONS: ("md", False),
    },
    DashboardMode.CRISIS: {
        SectionId.NOTIFICATIONS: ("lg", False), SectionId.APPROVALS: ("lg", False),
        SectionId.HERO: ("md", False), SectionId.PRIORITY: ("md", False),
        SectionId.TODAY: ("sm", True), SectionId.WORKING_MEMORY: ("sm", True),
    },
}


def default_layout(mode: DashboardMode, focus: str | None = None) -> LayoutState:
    """The fixed default layout for a mode. Approvals are ALWAYS visible (never hidden by default)."""
    emphasis = _MODE_EMPHASIS.get(mode, {})
    sections = []
    for order, sid in enumerate(_ALL):
        size, collapsed = emphasis.get(sid, ("md", False))
        sections.append(
            DashboardSection(id=sid, visible=True, collapsed=collapsed, size=size, order=order)
        )
    return LayoutState(mode=mode, sections=sections, focus=focus)


def validate_command(current: LayoutState, cmd: LayoutCommand) -> LayoutState | None:
    """Apply a validated layout command, or return None if the command is invalid (keep current)."""
    sections = {s.id: s.model_copy() for s in current.sections}
    layout = current.model_copy(deep=True)

    if cmd.action == "reorder":
        if not cmd.order or set(cmd.order) != set(_ALL):
            return None  # must be a full, valid permutation
        for order, sid in enumerate(cmd.order):
            sections[sid].order = order
    elif cmd.action in ("show", "hide"):
        if cmd.section is None:
            return None
        # Approvals may never be hidden — a pending write must always be reachable (safety).
        if cmd.action == "hide" and cmd.section == SectionId.APPROVALS:
            return None
        sections[cmd.section].visible = cmd.action == "show"
    elif cmd.action in ("collapse", "expand"):
        if cmd.section is None:
            return None
        sections[cmd.section].collapsed = cmd.action == "collapse"
    elif cmd.action == "resize":
        if cmd.section is None or cmd.size not in _VALID_SIZES:
            return None
        sections[cmd.section].size = cmd.size
    elif cmd.action == "set_focus":
        layout.focus = (cmd.focus or "").strip() or None
    elif cmd.action == "open_workspace":
        if not cmd.workspace:
            return None
        layout.last_workspace = cmd.workspace
    else:
        return None  # unknown action → ignore

    layout.sections = sorted(sections.values(), key=lambda s: s.order)
    return layout


# --- persistence (visual/preference state only) -----------------------------------------------


async def load_layout(account: str = "default") -> LayoutState | None:
    async with get_session() as session:
        row = (
            await session.execute(
                select(DashboardPref).where(DashboardPref.account == account)
            )
        ).scalar_one_or_none()
    if row is None or not row.layout:
        return None
    try:
        state = LayoutState.model_validate(row.layout)
    except Exception:  # noqa: BLE001 — a corrupt stored layout must never break the dashboard.
        return None
    state.focus = row.focus
    state.last_workspace = row.last_workspace
    return state


async def save_layout(layout: LayoutState, account: str = "default") -> None:
    async with get_session() as session:
        row = (
            await session.execute(
                select(DashboardPref).where(DashboardPref.account == account)
            )
        ).scalar_one_or_none()
        if row is None:
            row = DashboardPref(account=account)
            session.add(row)
        row.layout = layout.model_dump(mode="json")
        row.focus = layout.focus
        row.last_workspace = layout.last_workspace
        await session.commit()
