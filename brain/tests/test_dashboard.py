"""Backend tests for the Phase 2F.0 dashboard: modes, focus, layout, aggregation, API, safety."""
from datetime import UTC, datetime, timedelta

from httpx import ASGITransport, AsyncClient

from app import knowledge
from app.calendar_actions import store as approvals_store
from app.config import get_settings
from app.context import deadlines as deadlines_mod
from app.coordination import waiting as waiting_mod
from app.dashboard import aggregate, focus as focus_mod, layout as layout_mod, modes
from app.dashboard.contracts import (
    DashboardMode,
    LayoutCommand,
    PriorityItem,
    SectionId,
    SourceState,
    TruthBadge,
)
from app.knowledge.model import Conflict, Fact, Reality, WorldModel
from app.main import app
from app.sources import registry
from app.sources.registry import CALENDAR, GMAIL, SourceReport, SourceStatus


def _auth():
    return {"Authorization": f"Bearer {get_settings().auth_shared_token}"}


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


# --- deterministic mode selection ---------------------------------------------------------------


def test_mode_crisis_on_imminent_approval():
    s = modes.ModeSignals(approvals_pending=1, soonest_approval_expiry_minutes=5)
    assert modes.select_mode(s) is DashboardMode.CRISIS


def test_mode_pre_event_within_hour():
    s = modes.ModeSignals(minutes_to_next_event=30)
    assert modes.select_mode(s) is DashboardMode.PRE_EVENT


def test_mode_travel_beats_pre_event():
    s = modes.ModeSignals(minutes_to_next_event=45, next_event_is_travel=True)
    assert modes.select_mode(s) is DashboardMode.TRAVEL


def test_mode_deadline():
    s = modes.ModeSignals(minutes_to_next_event=600, top_deadline_urgency="high")
    assert modes.select_mode(s) is DashboardMode.DEADLINE


def test_mode_deep_work_needs_focus_and_clear_calendar():
    assert modes.select_mode(modes.ModeSignals(focus="college", minutes_to_next_event=None)) is DashboardMode.DEEP_WORK
    assert modes.select_mode(modes.ModeSignals(minutes_to_next_event=None)) is DashboardMode.IDLE


# --- focus never hides urgency ------------------------------------------------------------------


def test_focus_keeps_urgent_first():
    urgent = PriorityItem(title="Meeting now", urgent=True, confidence=0.9)
    focused = PriorityItem(title="College essay", confidence=0.5)
    other = PriorityItem(title="ARISE watch party", confidence=0.8)
    ranked = focus_mod.apply_focus([focused, other, urgent], focus="college")
    assert ranked[0].title == "Meeting now"           # urgent objective fact stays on top
    assert ranked[1].title == "College essay"          # focus match beats higher-confidence other
    assert len(ranked) == 3                              # nothing dropped


# --- layout defaults + validated commands -------------------------------------------------------


def test_default_layout_always_shows_approvals():
    for mode in DashboardMode:
        layout = layout_mod.default_layout(mode)
        approvals = next(s for s in layout.sections if s.id == SectionId.APPROVALS)
        assert approvals.visible is True


def test_validate_command_reorder_requires_full_permutation():
    current = layout_mod.default_layout(DashboardMode.IDLE)
    bad = layout_mod.validate_command(current, LayoutCommand(action="reorder", order=[SectionId.HERO]))
    assert bad is None
    good_order = [SectionId.APPROVALS, SectionId.HERO, SectionId.PRIORITY,
                  SectionId.TODAY, SectionId.WORKING_MEMORY, SectionId.NOTIFICATIONS]
    good = layout_mod.validate_command(current, LayoutCommand(action="reorder", order=good_order))
    assert good is not None and good.sections[0].id == SectionId.APPROVALS


def test_cannot_hide_approvals():
    current = layout_mod.default_layout(DashboardMode.IDLE)
    assert layout_mod.validate_command(current, LayoutCommand(action="hide", section=SectionId.APPROVALS)) is None


def test_invalid_resize_and_unknown_action_rejected():
    current = layout_mod.default_layout(DashboardMode.IDLE)
    assert layout_mod.validate_command(current, LayoutCommand(action="resize", section=SectionId.HERO, size="huge")) is None
    assert layout_mod.validate_command(current, LayoutCommand(action="teleport")) is None


# --- aggregation (mocked services, no live calls, no fabrication) --------------------------------


def _now():
    return datetime.now(UTC)


def _world(events=(), commitments=(), emails=(), conflicts=()):
    w = WorldModel(intent="schedule")
    w.events = list(events)
    w.commitments = list(commitments)
    w.emails = list(emails)
    w.conflicts = list(conflicts)
    w.sources = {}
    return w


def _patch_services(monkeypatch, *, world, connected=True, deadlines=(), waits=(), pending=()):
    async def q(**kwargs):
        return world

    def rep(name):
        st = SourceStatus.CONNECTED if connected else SourceStatus.DISCONNECTED
        return SourceReport(name=name, status=st, detail="ok")

    async def allr(account="default"):
        return {CALENDAR: rep(CALENDAR), GMAIL: rep(GMAIL)}

    async def dls(account="default"):
        return list(deadlines)

    async def lw(account="default"):
        return list(waits)

    async def lp(account=None):
        return list(pending)

    monkeypatch.setattr(knowledge, "query", q)
    monkeypatch.setattr(registry, "all_reports", allr)
    monkeypatch.setattr(deadlines_mod, "aggregate_deadlines", dls)
    monkeypatch.setattr(waiting_mod, "list_waiting", lw)
    monkeypatch.setattr(approvals_store, "list_pending", lp)


async def test_build_state_hero_from_imminent_event(monkeypatch):
    start = _now() + timedelta(minutes=40)
    ev = Fact(kind="event", reality=Reality.VERIFIED, text="Interview", source="calendar",
              provider_object_id="e1", confidence=0.95, when=start,
              data={"summary": "Interview with NYU", "location": "Manhattan", "attendees": ["dana@nyu.edu"]})
    _patch_services(monkeypatch, world=_world(events=[ev]))
    state = await aggregate.build_state()
    assert state.mode is DashboardMode.PRE_EVENT
    assert state.hero.present and state.hero.title == "Interview with NYU"
    assert TruthBadge.VERIFIED in state.hero.badges
    assert state.top_status.next_event_countdown_seconds is not None


async def test_build_state_never_fabricates_placeholder_sources(monkeypatch):
    _patch_services(monkeypatch, world=_world(), connected=False)
    state = await aggregate.build_state()
    by = {s.name: s for s in state.sources}
    assert by["weather"].placeholder and by["weather"].connected is False
    assert by["weather"].state is SourceState.COMING_LATER
    assert by["calendar"].connected is False
    assert state.hero.present is False  # no data → no invented hero


async def test_build_state_surfaces_conflict(monkeypatch):
    com = Fact(kind="commitment", reality=Reality.REMEMBERED, text="ECE ML Lab: weekdays 10-2",
               source="commitment", entity="ECE ML Lab", confidence=0.7,
               data={"recurrence": "RRULE"})
    conflict = Conflict(entity="ECE ML Lab", kind="schedule",
                        explanation="You told me weekdays 10-2 but I can't verify it in Google Calendar.")
    _patch_services(monkeypatch, world=_world(commitments=[com], conflicts=[conflict]))
    state = await aggregate.build_state()
    assert any(n.kind == "conflict" for n in state.notifications)
    assert state.today.conflicts


# --- API + safety -------------------------------------------------------------------------------


async def test_state_requires_auth():
    async with await _client() as c:
        assert (await c.get("/dashboard/state")).status_code == 401


async def test_state_endpoint_ok(monkeypatch):
    _patch_services(monkeypatch, world=_world())
    async with await _client() as c:
        resp = await c.get("/dashboard/state", headers=_auth())
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] in [m.value for m in DashboardMode]
    assert any(s["placeholder"] for s in body["sources"])


async def test_layout_post_valid_and_unsafe(monkeypatch):
    async with await _client() as c:
        ok = await c.post("/dashboard/layout", headers=_auth(),
                          json={"action": "resize", "section": "hero", "size": "lg"})
        assert ok.status_code == 200 and any(s["id"] == "hero" and s["size"] == "lg" for s in ok.json()["sections"])
        blocked = await c.post("/dashboard/layout", headers=_auth(),
                               json={"action": "hide", "section": "approvals"})
        assert blocked.status_code == 422  # approvals can never be hidden
