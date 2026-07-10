"""Deterministic parsing of commitment corrections and recurrence specs (Phase 2D.2).

Two shapes matter here, both plain regex/keyword (no LLM):
  • a naming correction — "it is ECE Machine Learning Lab", "it's actually Physics 101" — which tells
    us what a thing is really called (updates a commitment, never the calendar), and
  • a recurrence spec — "it's every weekday 10–2", "every Monday at 3" — which describes a repeating
    schedule (stored as evidence and turned into a CONFIRM-required recurring-create proposal).

Recognizing everything is not the goal; recognizing these common corrections reliably — and returning
None otherwise so the message falls through to normal handling — is.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import time

_WEEKDAYS = {
    "monday": "MO", "mon": "MO",
    "tuesday": "TU", "tue": "TU", "tues": "TU",
    "wednesday": "WE", "wed": "WE",
    "thursday": "TH", "thu": "TH", "thurs": "TH",
    "friday": "FR", "fri": "FR",
    "saturday": "SA", "sat": "SA",
    "sunday": "SU", "sun": "SU",
}
_WEEKDAY_ORDER = ["MO", "TU", "WE", "TH", "FR", "SA", "SU"]

# A recurrence is only inferred when an explicit repeat marker is present.
_RECUR_MARKERS = ("every", "each", "weekly", "daily", "weekdays", "weekday", "recurring", "repeats")


@dataclass(frozen=True)
class RecurrenceSpec:
    """A parsed repeating schedule. `rrule` is a Google-ready RRULE line. Pure/testable."""

    rrule: str
    summary: str  # human-readable, e.g. "every weekday, 10:00 AM–2:00 PM"
    start_time: time | None = None
    end_time: time | None = None
    title: str | None = None  # an event name if the same message named one


@dataclass(frozen=True)
class NameCorrection:
    """A correction of what something is called. `title` keeps the user's original casing."""

    title: str


# "it is X" / "it's actually X" / "that's called X" / "the class is X" → capture X (original casing).
_NAME_RE = re.compile(
    r"^\s*(?:it['’]?s|it is|that['’]?s|that is|this is|the (?:class|course|event|meeting|job) is)\s+"
    r"(?:actually\s+|really\s+|called\s+|named\s+)?"
    r"(.+?)[\.\!]?\s*$",
    re.IGNORECASE,
)
_HAS_UPPER = re.compile(r"[A-Z]")
_HAS_LETTER = re.compile(r"[A-Za-z]")


# Bare-hour ranges ("10-2", "10 to 2") the calendar scanner skips — recurrence needs both endpoints.
_TIME_TOKEN = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)?\b")


def _meridiem_hour(hour: int, meridiem: str | None) -> int | None:
    """Business-hour heuristic: bare 1–7 → afternoon, 8–11 → morning, 12 → noon."""
    if hour > 23:
        return None
    if meridiem == "pm":
        return hour if hour == 12 else hour + 12
    if meridiem == "am":
        return 0 if hour == 12 else hour
    if hour == 12:
        return 12
    if 1 <= hour <= 7:
        return hour + 12
    return hour


def _times(text: str) -> list[time]:
    """Clock times in order — handles bare ranges like "10-2" (→ 10:00 and 2:00 PM)."""
    out: list[time] = []
    for m in _TIME_TOKEN.finditer(text.lower()):
        minute = int(m.group(2) or 0)
        hour = _meridiem_hour(int(m.group(1)), m.group(3))
        if hour is not None and 0 <= minute <= 59:
            out.append(time(hour, minute))
    return out


def _fmt_time(t: time) -> str:
    return t.strftime("%-I:%M %p").lstrip("0")


def _weekday_rule(lowered: str) -> tuple[str, str] | None:
    """(BYDAY clause, human phrase) for the recurrence, or None if no cadence is expressed."""
    if "weekday" in lowered or "weekdays" in lowered:
        return "FREQ=WEEKLY;BYDAY=MO,TU,WE,TH,FR", "every weekday"
    if "everyday" in lowered or "every day" in lowered or "daily" in lowered:
        return "FREQ=DAILY", "every day"
    found = [
        code
        for word, code in _WEEKDAYS.items()
        if re.search(rf"\b{word}\b", lowered)
    ]
    if found:
        ordered = [c for c in _WEEKDAY_ORDER if c in set(found)]
        days = ",".join(ordered)
        names = ", ".join(_day_name(c) for c in ordered)
        return f"FREQ=WEEKLY;BYDAY={days}", f"every {names}"
    if "every week" in lowered or "weekly" in lowered:
        return "FREQ=WEEKLY", "every week"
    return None


def _day_name(code: str) -> str:
    return {
        "MO": "Monday", "TU": "Tuesday", "WE": "Wednesday", "TH": "Thursday",
        "FR": "Friday", "SA": "Saturday", "SU": "Sunday",
    }[code]


def detect_recurrence(text: str) -> RecurrenceSpec | None:
    """Parse a repeating-schedule statement, or None. Requires an explicit repeat marker."""
    lowered = text.lower()
    if not any(re.search(rf"\b{m}\b", lowered) for m in _RECUR_MARKERS):
        return None
    rule = _weekday_rule(lowered)
    if rule is None:
        return None
    byday, cadence = rule

    times = _times(text)
    start_time = times[0] if times else None
    end_time = times[1] if len(times) >= 2 else None

    if start_time and end_time:
        when = f", {_fmt_time(start_time)}–{_fmt_time(end_time)}"
    elif start_time:
        when = f", at {_fmt_time(start_time)}"
    else:
        when = ""
    return RecurrenceSpec(
        rrule=f"RRULE:{byday}",
        summary=f"{cadence}{when}",
        start_time=start_time,
        end_time=end_time,
        title=None,
    )


def detect_name_correction(text: str) -> NameCorrection | None:
    """Parse "it is X" / "it's actually X" into a name, or None. Guards against catching chit-chat."""
    match = _NAME_RE.match(text.strip())
    if not match:
        return None
    name = match.group(1).strip(" \t\"'“”")
    # Guard: a real name is a proper noun (has an uppercase letter) or multi-word; and not a repeat
    # statement (those are recurrence specs, handled separately).
    if len(name) < 2 or not _HAS_LETTER.search(name):
        return None
    if any(re.search(rf"\b{m}\b", name.lower()) for m in _RECUR_MARKERS):
        return None
    # A real correction names a proper noun — require a capital so ordinary chit-chat ("that is
    # great, thanks") doesn't get mistaken for a name. Under-triggering is safe; guessing is not.
    if not _HAS_UPPER.search(name):
        return None
    return NameCorrection(title=name)
