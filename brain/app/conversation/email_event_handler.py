"""Search email for events/invitations — Phase 2D.3, defect R3.

"Check my email for upcoming events" used to be mis-routed to list_unread ("is:unread in:inbox"),
which ignored both "for events" and any follow-up name. Here it becomes a real Gmail search for
event-shaped messages, optionally scoped to a person. This is the BASIC version: 2D.3b adds the deep
event-candidate intel (date/location/program-term ranking + Calendar cross-check). What matters now:
it actually searches, never denies the capability when Gmail is connected, and reports an empty result
honestly rather than inventing events.
"""
from __future__ import annotations

from datetime import UTC, datetime
from zoneinfo import ZoneInfo

from app.config import get_settings
from app.integrations.google import gmail
from app.query.answer import ProviderFact, StructuredAnswer
from app.security.crypto import EncryptionUnavailableError
from app.sources import registry
from app.telemetry import get_logger

log = get_logger(__name__)

_NOT_CONNECTED = (
    "I'm not connected to your Gmail yet, so I can't search it. Ask me to connect and grant "
    "read-only Gmail access first."
)
_NO_KEY = "I can't read your email yet — the encryption key isn't configured on the server."
_ERROR = "Sorry — I couldn't search your email just now. Try again in a moment."

# Event-shaped terms. Kept broad; 2D.3b will rank candidates and cross-check against the calendar.
_EVENT_QUERY = (
    '(invite OR invitation OR "calendar invite" OR event OR rsvp OR "you\'re invited" '
    'OR "save the date" OR meeting OR seminar OR webinar OR appointment)'
)
_SEARCH_WINDOW_DAYS = 60


def _tz() -> ZoneInfo:
    try:
        return ZoneInfo(get_settings().tz)
    except Exception:  # noqa: BLE001
        return ZoneInfo("UTC")


def _build_query(person: str | None) -> str:
    query = f"{_EVENT_QUERY} newer_than:{_SEARCH_WINDOW_DAYS}d"
    if person:
        # Match the name as sender or anywhere in the message — Gmail handles bare names loosely.
        query = f'(from:{person} OR "{person}") {query}'
    return query


def _fmt_message(msg: gmail.GmailMessage, tz: ZoneInfo) -> str:
    who = msg.from_name or msg.from_email or "unknown sender"
    subject = msg.subject or "(no subject)"
    when = ""
    if msg.received_at:
        when = f" · {msg.received_at.astimezone(tz).strftime('%b %-d')}"
    return f"{subject} — from {who}{when}"


async def build_answer(text: str, person: str | None, account: str = "default") -> StructuredAnswer:
    report = await registry.gmail_report(account)
    scope = f" from {person}" if person else ""
    answer = StructuredAnswer(
        question=text,
        intent="email_event_search",
        source_status=[report],
        empty_state=(
            f"I searched your email for event-related messages{scope} and didn't find any "
            f"in the last {_SEARCH_WINDOW_DAYS} days."
        ),
    )
    if not report.connected:
        answer.headline = _NOT_CONNECTED
        return answer

    messages = await gmail.search(_build_query(person), account=account)
    tz = _tz()
    messages.sort(key=lambda m: m.received_at or datetime.min.replace(tzinfo=UTC), reverse=True)
    for msg in messages:
        if not msg.gmail_id:
            continue
        answer.provider_facts.append(
            ProviderFact(
                source="gmail",
                provider_object_id=msg.gmail_id,
                text=_fmt_message(msg, tz),
                when=msg.received_at,
            )
        )
    if answer.provider_facts:
        answer.headline = f"I found these event-related emails{scope}:"
    return answer


async def handle(text: str, person: str | None = None, account: str = "default") -> str:
    """Search email for event-related messages, optionally scoped to a person. Never raises."""
    try:
        answer = await build_answer(text, person, account)
    except gmail.NotConnectedError:
        return _NOT_CONNECTED
    except EncryptionUnavailableError:
        return _NO_KEY
    except Exception as exc:  # noqa: BLE001 — friendly to user, detail to logs.
        log.error("email_event_search_failed", error=str(exc), error_type=type(exc).__name__)
        return _ERROR
    return answer.render() or answer.empty_state or _ERROR
