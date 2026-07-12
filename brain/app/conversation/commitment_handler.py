"""Chat glue for durable commitments (Phase 2D.2) — corrections and recurring-schedule proposals.

Two jobs, both routed before the generic LLM fallback:
  • a naming correction ("it is ECE Machine Learning Lab") updates our commitment memory and replies
    WITHOUT ever claiming a calendar change — updating memory is not touching the calendar; and
  • a recurrence statement ("it's every weekday 10–2") is stored as evidence AND drafted into a
    CONFIRM-required recurring-create proposal — no write happens until the user confirms.

Returns a reply string when it handled the message, or None to let other routes / the LLM take it.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from app.calendar_actions import store
from app.calendar_actions.schema import ActionType
from app.commitments import parse as cparse
from app.commitments import store as commitments
from app.commitments.parse import RecurrenceSpec
from app.config import get_settings
from app.knowledge import entities
from app.reasoning import reconcile
from app.telemetry import get_logger

log = get_logger(__name__)

_CONFIRM_SUFFIX = "\n\nReply CONFIRM to add this recurring event, or anything else to hold off."
_BYDAY_TO_WEEKDAY = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


async def handle(
    text: str, *, account: str = "default", channel: str = "telegram", external_id: str | None = None
) -> str | None:
    """Handle a correction / recurrence statement, or return None to fall through."""
    spec = cparse.detect_recurrence(text)
    if spec is not None:
        return await _handle_recurrence(spec, account, channel, external_id)
    correction = cparse.detect_name_correction(text)
    if correction is not None:
        return await _handle_naming(correction.title, account)
    return None


async def _handle_naming(title: str, account: str) -> str:
    """Record what a thing is really called. Memory only — never a calendar change, never claims one.

    Also records a PERMANENT alias in the knowledge store: whatever the prior referent was (the most
    recent commitment) becomes an alias of this corrected name, so every future knowledge query for the
    old name resolves automatically (Phase 2D.3, behaviors 7/8).
    """
    prior = await commitments.latest(account)
    await commitments.upsert(
        account=account, title=title, confidence=0.7, evidence_source="conversation"
    )
    try:
        old_name = prior.title if prior is not None else title
        await entities.record_correction(
            old_name, title, entity_type="commitment", account=account
        )
    except Exception as exc:  # noqa: BLE001 — an alias-store hiccup must never break the reply.
        log.warning("record_correction_failed", error=str(exc))
    await reconcile.note_correction(account, title)  # fold the correction into the life graph
    return (
        f"Got it — I'll remember this as “{title}”. "
        "(I've noted that for myself; I haven't changed anything on your calendar.)"
    )


def _byday(rrule: str) -> list[int]:
    for part in rrule.replace("RRULE:", "").split(";"):
        if part.startswith("BYDAY="):
            return [
                _BYDAY_TO_WEEKDAY[c]
                for c in part[len("BYDAY="):].split(",")
                if c in _BYDAY_TO_WEEKDAY
            ]
    return []


def _first_occurrence(spec: RecurrenceSpec, tz: ZoneInfo) -> tuple[datetime, datetime]:
    """The first concrete instance (DTSTART) implied by the recurrence — a real, dated start/end."""
    settings = get_settings()
    start_time = spec.start_time or time(settings.workday_start_hour, 0)
    today = datetime.now(tz).date()
    days = _byday(spec.rrule)
    offset = 0
    if days:
        while (today + timedelta(days=offset)).weekday() not in days:
            offset += 1
            if offset > 7:  # safety — should never happen with a valid BYDAY
                break
    day = today + timedelta(days=offset)
    start = datetime.combine(day, start_time, tzinfo=tz)
    if spec.end_time is not None:
        end = datetime.combine(day, spec.end_time, tzinfo=tz)
        if end <= start:  # crossed midnight / bad range → fall back to default duration
            end = start + timedelta(minutes=settings.default_event_duration_minutes)
    else:
        end = start + timedelta(minutes=settings.default_event_duration_minutes)
    return start, end


async def _handle_recurrence(
    spec: RecurrenceSpec, account: str, channel: str, external_id: str | None
) -> str:
    """Store the recurrence as evidence and draft a CONFIRM-required recurring-create proposal."""
    title = spec.title
    if title is None:
        recent = await commitments.latest(account)
        title = recent.title if recent else None
    if not title:
        # We know the cadence but not what it's for — ask rather than invent a title.
        return (
            f"Got it — {spec.summary}. What should I call it? "
            "Tell me the name and I'll draft it for you to CONFIRM."
        )

    # Update our understanding (memory only — no calendar write yet).
    await commitments.upsert(
        account=account,
        title=title,
        schedule_summary=spec.summary,
        recurrence=spec.rrule,
        confidence=0.7,
        evidence_source="conversation",
    )
    # Fold the stated schedule into the life graph as a Remembered, evidence-backed fact so the
    # reasoning layer + dashboard reflect it immediately (the calendar create still needs CONFIRM).
    await reconcile.note_commitment(
        account, title, schedule_summary=spec.summary, recurrence=spec.rrule
    )

    tz = _tz()
    start, end = _first_occurrence(spec, tz)
    summary = f"Add “{title}” — {spec.summary} — starting {start.strftime('%a %b %-d')}."
    payload = {
        "summary": title,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "location": None,
        "recurrence": [spec.rrule],
    }
    row = await store.draft(
        action_type=ActionType.CREATE,
        summary=summary,
        payload=payload,
        channel=channel,
        external_id=external_id,
        account=account,
    )
    log.info("recurring_create_drafted", account=account, action_id=row.id, title=title)
    return summary + _CONFIRM_SUFFIX
