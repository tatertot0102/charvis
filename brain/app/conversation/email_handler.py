"""Dispatch an email intent to the right read-only Gmail call and format a chat reply.

Shared by Telegram and /chat via the conversation service. All Gmail work is read-only; errors
degrade to a friendly message while the detail goes to the logs.
"""
from __future__ import annotations

from datetime import UTC, datetime

from app.config import get_settings
from app.conversation.intents import EmailIntent
from app.coordination import waiting
from app.integrations.google import gmail, gmail_format, sync
from app.lifemodel import people
from app.security.crypto import EncryptionUnavailableError
from app.telemetry import get_logger

log = get_logger(__name__)

_NOT_CONNECTED = (
    "I'm not connected to your Gmail yet. Send /connect_google and grant Gmail read access "
    "(re-consent if you only linked Calendar before)."
)
_NO_KEY = "I can't read your email yet — the encryption key isn't configured on the server."
_ERROR = "Sorry — I couldn't reach your email just now. Try again in a moment."


async def handle(intent: EmailIntent, arg: str | None) -> str:
    """Answer an email intent. Never raises — returns user-facing text."""
    limit = get_settings().gmail_unread_max
    try:
        my_email = await gmail.get_profile_email()

        if intent is EmailIntent.UNREAD:
            messages = await gmail.list_unread(max_results=limit)
            return gmail_format.format_unread(messages, my_email)

        if intent is EmailIntent.IMPORTANT:
            messages = await gmail.list_unread(max_results=limit)
            return gmail_format.format_important(messages, my_email)

        if intent is EmailIntent.SUMMARIZE:
            messages = await gmail.list_today(max_results=limit)
            return gmail_format.format_summary(messages, my_email)

        if intent is EmailIntent.WAITING:
            await sync.sync_recent()
            items = await waiting.list_waiting()
            return gmail_format.format_waiting(items, datetime.now(UTC))

        if intent is EmailIntent.DID_REPLY and arg:
            person = await people.find_person(arg)
            sender = person.email if person else arg
            messages = await gmail.search(f"from:{sender} newer_than:60d", max_results=limit)
            return gmail_format.format_did_reply(arg, messages, my_email)

        # Unknown/degenerate intent — let the caller fall back to the model.
        return _ERROR
    except gmail.NotConnectedError:
        return _NOT_CONNECTED
    except EncryptionUnavailableError:
        return _NO_KEY
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("email_intent_failed", intent=intent.value, error=str(exc), error_type=type(exc).__name__)
        return _ERROR
