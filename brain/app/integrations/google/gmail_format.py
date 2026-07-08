"""Human-friendly text rendering of Gmail results for chat replies (Telegram / on-demand).

Pure formatting over GmailMessage + Classification + WaitingItem — no I/O, easy to unit-test.
"""
from __future__ import annotations

from datetime import datetime

from app.db.models import WaitingItem
from app.integrations.google.classify import classify
from app.integrations.google.gmail import GmailMessage

_MAX_LINES = 12


def _who(msg: GmailMessage) -> str:
    return msg.from_name or msg.from_email or "(unknown sender)"


def _line(msg: GmailMessage, my_email: str) -> str:
    classification = classify(msg, my_email)
    marker = "🔴" if msg.is_unread else "•"
    tags: list[str] = []
    if classification.requires_response:
        tags.append("needs reply")
    if classification.is_deadline_related:
        tags.append("deadline")
    if classification.is_calendar_related:
        tags.append("calendar")
    suffix = f"  [{', '.join(tags)}]" if tags else ""
    subject = (msg.subject or "(no subject)").strip()
    return f"{marker} {_who(msg)} — {subject}{suffix}"


def format_unread(messages: list[GmailMessage], my_email: str) -> str:
    real = [m for m in messages if not classify(m, my_email).is_promotional]
    if not real:
        return "No unread email that needs you. 📭"
    lines = [f"You have {len(real)} unread email{'s' if len(real) != 1 else ''}:"]
    lines += [_line(m, my_email) for m in real[:_MAX_LINES]]
    if len(real) > _MAX_LINES:
        lines.append(f"…and {len(real) - _MAX_LINES} more.")
    return "\n".join(lines)


def format_important(messages: list[GmailMessage], my_email: str) -> str:
    important = [
        m
        for m in messages
        if (c := classify(m, my_email)).importance == "high"
        or c.requires_response
        or c.is_deadline_related
    ]
    if not important:
        return "Nothing looks urgent right now. ✅"
    lines = ["Here's what looks important:"]
    lines += [_line(m, my_email) for m in important[:_MAX_LINES]]
    return "\n".join(lines)


def format_summary(messages: list[GmailMessage], my_email: str) -> str:
    if not messages:
        return "No email in the last day. 📭"
    unread = needs_reply = promotional = calendar = deadline = 0
    for msg in messages:
        classification = classify(msg, my_email)
        unread += msg.is_unread
        needs_reply += classification.requires_response
        promotional += classification.is_promotional
        calendar += classification.is_calendar_related
        deadline += classification.is_deadline_related

    lines = [
        f"Today's email — {len(messages)} message{'s' if len(messages) != 1 else ''}:",
        f"• {unread} unread",
        f"• {needs_reply} need a reply",
    ]
    if deadline:
        lines.append(f"• {deadline} mention a deadline")
    if calendar:
        lines.append(f"• {calendar} calendar-related")
    if promotional:
        lines.append(f"• {promotional} promotional/FYI")

    top = [m for m in messages if classify(m, my_email).requires_response][:5]
    if top:
        lines.append("\nMost likely to need you:")
        lines += [_line(m, my_email) for m in top]
    return "\n".join(lines)


def format_did_reply(name: str, messages: list[GmailMessage], my_email: str) -> str:
    inbound = [m for m in messages if classify(m, my_email).direction == "inbound"]
    if not inbound:
        return f"No — I don't see a recent reply from {name}."
    latest = max(inbound, key=lambda m: m.received_at or datetime.min)
    when = latest.received_at.strftime("%b %-d") if latest.received_at else "recently"
    unread_note = " (unread)" if latest.is_unread else ""
    subject = (latest.subject or "(no subject)").strip()
    return f"Yes — {name} emailed you on {when}{unread_note}: “{subject}”."


def format_waiting(items: list[WaitingItem], now: datetime) -> str:
    if not items:
        return "You're not waiting on anyone, and no one's waiting on you. 🎉"
    them = [i for i in items if i.kind == "waiting_on_them"]
    me = [i for i in items if i.kind == "waiting_on_me"]
    lines: list[str] = []

    if them:
        lines.append("⏳ Waiting on them:")
        for item in them[:_MAX_LINES]:
            days = (now - item.last_message_at).days if item.last_message_at else 0
            nudge = "  ← follow up?" if item.follow_up_recommended else ""
            who = item.person_email or "someone"
            lines.append(f"• {who} — {item.subject or '(no subject)'} ({days}d){nudge}")
    if me:
        if lines:
            lines.append("")
        lines.append("📨 Waiting on you to reply:")
        for item in me[:_MAX_LINES]:
            days = (now - item.last_message_at).days if item.last_message_at else 0
            who = item.person_email or "someone"
            lines.append(f"• {who} — {item.subject or '(no subject)'} ({days}d)")
    return "\n".join(lines)
