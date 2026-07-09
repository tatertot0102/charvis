"""Dispatch a cross-source context intent to the ContextResolver and format a chat reply.

Shared by Telegram and /chat via the conversation service. Read-only; every branch degrades to a
friendly message on failure while the detail goes to the logs. This is the "combine, don't dump"
layer — replies synthesize Calendar + Gmail + waiting-on rather than listing raw data.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.context import briefing, deadlines, resolver
from app.conversation.intents import ContextIntent
from app.coordination import waiting
from app.integrations.google import calendar, gmail
from app.memory import next_action
from app.security.crypto import EncryptionUnavailableError
from app.telemetry import get_logger

log = get_logger(__name__)

_NOT_CONNECTED = (
    "I'm not connected to your Google account yet. Send /connect_google and grant read access "
    "to Calendar + Gmail."
)
_NO_KEY = "I can't read your data yet — the encryption key isn't configured on the server."
_ERROR = "Sorry — I couldn't pull that together just now. Try again in a moment."
_NO_MEETING = "You have no upcoming meetings on your calendar. 🎉"


async def handle(intent: ContextIntent) -> str:
    """Answer a context intent. Never raises — returns user-facing text."""
    try:
        if intent is ContextIntent.PREP_MEETING:
            context = await resolver.resolve_next_meeting()
            if context is None:
                return _NO_MEETING
            return await briefing.generate_briefing(context)

        if intent is ContextIntent.MEETING_ABOUT:
            context = await resolver.resolve_next_meeting()
            if context is None:
                return _NO_MEETING
            return briefing.format_did_summary_line(context)

        if intent is ContextIntent.EVENT_EMAILS:
            context = await resolver.resolve_next_meeting()
            if context is None:
                return _NO_MEETING
            if not context.related_emails:
                return f"I couldn't find emails related to “{context.event.summary}”."
            lines = [f"Emails related to “{context.event.summary}”:"]
            for item in context.related_emails:
                who = item.message.from_name or item.message.from_email
                subject = (item.message.subject or "(no subject)").strip()
                lines.append(f"• {who} — {subject} ({item.reason})")
            return "\n".join(lines)

        if intent is ContextIntent.DEADLINES:
            items = await deadlines.aggregate_deadlines()
            return briefing.format_deadlines(items, datetime.now(UTC))

        if intent is ContextIntent.NEXT_ACTION:
            context = None
            try:
                context = await resolver.resolve_next_meeting()
            except calendar.NotConnectedError:
                return _NOT_CONNECTED
            try:
                wait_items = await waiting.list_waiting()
            except Exception:  # noqa: BLE001
                wait_items = []
            dls = await deadlines.aggregate_deadlines()
            memory_hint = await next_action.suggest_from_memory()
            return briefing.format_next_action(context, wait_items, dls, memory_hint=memory_hint)

        return _ERROR
    except (gmail.NotConnectedError, calendar.NotConnectedError):
        return _NOT_CONNECTED
    except EncryptionUnavailableError:
        return _NO_KEY
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error(
            "context_intent_failed",
            intent=intent.value,
            error=str(exc),
            error_type=type(exc).__name__,
        )
        return _ERROR
