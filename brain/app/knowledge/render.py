"""Deterministic, reality-labelled prose from a WorldModel (Phase 2D.3 integration).

The final "explanation" step. It never invents — it only describes what the WorldModel already holds,
and it keeps the four realities visually separate (Verified / Likely / Remembered / Inferred) so the
user always knows what's provider-confirmed versus what Jarvis merely remembers or infers. Conflicts
are stated, never hidden. This is what the conversation layer sends; a dashboard can read the same
WorldModel and lay it out differently.
"""
from __future__ import annotations

from datetime import date
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.knowledge.model import Reality, WorldModel


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _calendar_down(world: WorldModel) -> bool:
    report = world.sources.get("calendar")
    return report is not None and not report.connected


def explain_schedule(world: WorldModel, label: str) -> str:
    """Render a ranged schedule answer: real events by day, plus remembered/likely context + conflicts."""
    if not world.events and _calendar_down(world):
        return (
            "I'm not connected to your Google Calendar yet, so I can't read your schedule. "
            "Ask me to connect first."
        )

    parts: list[str] = []
    if world.events:
        parts.append(_events_by_day(world, label))
    else:
        parts.append(f"You have nothing on your calendar {label}. 🎉")

    remembered = [f for f in world.commitments if f.reality is Reality.REMEMBERED]
    if remembered:
        lines = ["You've also told me about (not from your calendar):"]
        lines += [f"  • {f.text}" for f in remembered[:6]]
        parts.append("\n".join(lines))

    invites = [f for f in world.emails if f.reality is Reality.LIKELY]
    if invites:
        lines = ["Possibly relevant email invitations (not yet confirmed on your calendar):"]
        lines += [f"  • {f.text}" for f in invites[:5]]
        parts.append("\n".join(lines))

    parts.extend(_conflict_lines(world))
    return "\n\n".join(p for p in parts if p).strip()


def explain_entity(world: WorldModel, name: str) -> str:
    """Render "what is X / what is X related to" by merging every provider, grouped by reality."""
    if not world.has_facts():
        return (
            f"I don't have anything on “{name}” yet — nothing in your calendar, email, commitments, "
            f"or what you've told me. Tell me more and I'll remember it."
        )

    parts = [f"Here's what I know about “{name}”:"]
    sections = [
        (Reality.VERIFIED, "✓ Verified (from Google)", world.events),
        (Reality.LIKELY, "~ Likely (from email)", world.emails + world.waiting),
        (Reality.REMEMBERED, "• Remembered (you told me)",
         world.commitments + world.memory + world.messages),
        (Reality.INFERRED, "? Inferred (a pattern I noticed)", world.patterns),
    ]
    for reality, header, facts in sections:
        rel = [f for f in facts if f.reality is reality]
        if not rel:
            continue
        lines = [header + ":"]
        lines += [f"  • {f.text}" for f in rel[:6]]
        parts.append("\n".join(lines))

    parts.extend(_conflict_lines(world))
    return "\n\n".join(p for p in parts if p).strip()


def explain_email_events(world: WorldModel, person: str | None = None) -> str:
    """Render an email event-search: event-shaped messages, flagging any already on the calendar."""
    gmail = world.sources.get("gmail")
    if gmail is not None and not gmail.connected:
        return (
            "I'm not connected to your Gmail yet, so I can't search it. Ask me to connect and grant "
            "read-only Gmail access first."
        )
    scope = f" from {person}" if person else ""
    if not world.emails:
        return (
            f"I searched your email for event-related messages{scope} and didn't find any recent ones."
        )
    lines = [f"I found these event-related emails{scope}:"]
    for email in world.emails[:10]:
        tag = " — already on your calendar ✓" if email.data.get("on_calendar") else ""
        lines.append(f"• {email.text}{tag}")
    return "\n".join(lines)


def explain_verify(world: WorldModel, subject: str) -> str:
    """Render "is X on my calendar?" from verified events only — a truthful yes/no, never a guess."""
    cal = world.sources.get("calendar")
    if cal is not None and not cal.connected:
        return "I'm not connected to your Google Calendar yet, so I can't check. Ask me to connect first."
    found = world.events
    if not found:
        return (
            f"No — I don't see anything matching “{subject}” on your Google Calendar. "
            f"I'm not going to guess one exists."
        )
    if len(found) == 1:
        f = found[0]
        return f"Yes — “{f.data.get('summary') or f.text}” is on your Google Calendar: {_when(f)}."
    lines = [f"Yes — I see {len(found)} matching events on your Google Calendar:"]
    for f in found[:5]:
        lines.append(f"• {f.data.get('summary') or f.text} — {_when(f)}")
    return "\n".join(lines)


def _when(fact) -> str:
    if fact.when is None:
        return "date unknown"
    return fact.when.astimezone(_tz()).strftime("%A %b %-d at %-I:%M %p").replace(" at 12:00 AM", "")


def _events_by_day(world: WorldModel, label: str) -> str:
    tz = _tz()
    by_day: dict[date, list[str]] = {}
    for fact in world.events:
        day = fact.when.astimezone(tz).date() if fact.when else None
        summary = fact.data.get("summary") or fact.text
        line = _time_line(fact, tz, summary)
        by_day.setdefault(day, []).append(line)
    lines = [f"Here's your {label}:"]
    for day in sorted([d for d in by_day if d is not None]):
        lines.append(f"\n{day.strftime('%A %b %-d')}:")
        for entry in by_day[day]:
            lines.append(f"  • {entry}")
    for entry in by_day.get(None, []):
        lines.append(f"  • {entry}")
    return "\n".join(lines)


def _time_line(fact, tz, summary: str) -> str:
    if fact.data.get("cached") or fact.when is None:
        return summary
    local = fact.when.astimezone(tz)
    where = f" @ {fact.data.get('location')}" if fact.data.get("location") else ""
    return f"{local.strftime('%-I:%M %p')} — {summary}{where}"


def _conflict_lines(world: WorldModel) -> list[str]:
    if not world.conflicts:
        return []
    lines = ["⚠️ Worth flagging:"]
    for conflict in world.conflicts:
        lines.append(f"  • {conflict.explanation}")
    return ["\n".join(lines)]
