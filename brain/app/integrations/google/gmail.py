"""Read-only Gmail connector (Phase 2B).

READ ONLY. This module never sends, drafts, archives, deletes, labels, or otherwise modifies Gmail
— it only lists/gets messages and threads. The Google API client is synchronous, so every network
call is offloaded with asyncio.to_thread to keep the FastAPI event loop unblocked. Credentials are
loaded from the shared encrypted store built in Phase 2A (no auth duplication).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from email.utils import parseaddr, parsedate_to_datetime

import asyncio

from google.auth.exceptions import GoogleAuthError
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.integrations.google import tokens
from app.telemetry import get_logger

log = get_logger(__name__)

DEFAULT_MAX_RESULTS = 20
MAX_THREADS_SCAN = 25
RECENT_THREAD_WINDOW_DAYS = 14
_METADATA_HEADERS = ["From", "To", "Cc", "Subject", "Date"]

# Cache the authenticated address per account — it never changes for a connected account, and it's
# needed to classify message direction (inbound vs outbound) without a getProfile call every time.
_profile_email_cache: dict[str, str] = {}


class NotConnectedError(RuntimeError):
    """Raised when Gmail can't be read yet — not connected, revoked, or missing the Gmail scope.

    A stored token that only granted the Calendar scope (Phase 2A) surfaces here on the first Gmail
    call, so callers uniformly prompt the user to (re-)connect and grant Gmail read access.
    """


def _is_auth_error(exc: BaseException) -> bool:
    if isinstance(exc, GoogleAuthError):
        return True  # refresh failed / token revoked
    if isinstance(exc, HttpError):
        return getattr(exc.resp, "status", None) in (401, 403)  # unauthorized / insufficient scope
    return False


@dataclass(frozen=True)
class GmailMessage:
    gmail_id: str
    thread_id: str
    from_email: str
    from_name: str | None
    to_emails: tuple[str, ...]
    subject: str
    snippet: str
    received_at: datetime | None
    labels: tuple[str, ...]

    @property
    def is_unread(self) -> bool:
        return "UNREAD" in self.labels


# --- header parsing (pure) ---------------------------------------------------


def _header(headers: list[dict], name: str) -> str:
    target = name.lower()
    for header in headers:
        if header.get("name", "").lower() == target:
            return header.get("value", "")
    return ""


def _parse_addr(value: str) -> tuple[str, str | None]:
    name, email = parseaddr(value)
    return email.lower(), (name or None)


def _parse_recipients(value: str) -> tuple[str, ...]:
    out: list[str] = []
    for part in value.split(","):
        if not part.strip():
            continue
        _, email = parseaddr(part)
        if email:
            out.append(email.lower())
    return tuple(out)


def _parse_date(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed


def _to_message(raw: dict) -> GmailMessage:
    payload = raw.get("payload", {})
    headers = payload.get("headers", [])
    from_email, from_name = _parse_addr(_header(headers, "From"))
    recipients = _parse_recipients(_header(headers, "To")) + _parse_recipients(
        _header(headers, "Cc")
    )
    return GmailMessage(
        gmail_id=raw.get("id", ""),
        thread_id=raw.get("threadId", ""),
        from_email=from_email,
        from_name=from_name,
        to_emails=recipients,
        subject=_header(headers, "Subject"),
        snippet=raw.get("snippet", ""),
        received_at=_parse_date(_header(headers, "Date")),
        labels=tuple(raw.get("labelIds", []) or []),
    )


# --- synchronous Google calls (always via asyncio.to_thread) -----------------


def _service(creds: Credentials):
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def _fetch_profile_email(creds: Credentials) -> str:
    profile = _service(creds).users().getProfile(userId="me").execute()
    return (profile.get("emailAddress") or "").lower()


def _fetch_messages(creds: Credentials, query: str, max_results: int) -> list[dict]:
    service = _service(creds)
    listing = (
        service.users().messages().list(userId="me", q=query, maxResults=max_results).execute()
    )
    messages = []
    for stub in listing.get("messages", []):
        messages.append(
            service.users()
            .messages()
            .get(
                userId="me", id=stub["id"], format="metadata", metadataHeaders=_METADATA_HEADERS
            )
            .execute()
        )
    return messages


def _fetch_thread(creds: Credentials, thread_id: str) -> list[dict]:
    thread = (
        _service(creds)
        .users()
        .threads()
        .get(userId="me", id=thread_id, format="metadata", metadataHeaders=_METADATA_HEADERS)
        .execute()
    )
    return thread.get("messages", [])


def _fetch_recent_threads(creds: Credentials, query: str, max_threads: int) -> list[list[dict]]:
    service = _service(creds)
    listing = service.users().threads().list(userId="me", q=query, maxResults=max_threads).execute()
    threads = []
    for stub in listing.get("threads", []):
        full = (
            service.users()
            .threads()
            .get(userId="me", id=stub["id"], format="metadata", metadataHeaders=_METADATA_HEADERS)
            .execute()
        )
        threads.append(full.get("messages", []))
    return threads


# --- async public API --------------------------------------------------------


async def _load_creds(account: str) -> Credentials:
    try:
        creds = await tokens.load_credentials(account)
    except GoogleAuthError as exc:  # refresh token revoked/expired
        raise NotConnectedError("Google credentials could not be refreshed — reconnect.") from exc
    if creds is None:
        raise NotConnectedError("Google is not connected.")
    return creds


async def _run_google(fn, *args):
    """Run a sync Google call off the event loop, mapping auth/scope failures to NotConnectedError."""
    try:
        return await asyncio.to_thread(fn, *args)
    except Exception as exc:  # noqa: BLE001 — re-raise unless it's an auth/scope error.
        if _is_auth_error(exc):
            raise NotConnectedError(
                "Google denied the request — reconnect and grant Gmail read access."
            ) from exc
        raise


def _sorted_messages(raw: list[dict]) -> list[GmailMessage]:
    messages = [_to_message(m) for m in raw]
    return sorted(messages, key=lambda m: m.received_at or datetime.min.replace(tzinfo=UTC))


async def get_profile_email(account: str = "default") -> str:
    cached = _profile_email_cache.get(account)
    if cached:
        return cached
    creds = await _load_creds(account)
    email = await _run_google(_fetch_profile_email, creds)
    if email:
        _profile_email_cache[account] = email
    return email


async def list_unread(
    account: str = "default", max_results: int = DEFAULT_MAX_RESULTS
) -> list[GmailMessage]:
    creds = await _load_creds(account)
    raw = await _run_google(_fetch_messages, creds, "is:unread in:inbox", max_results)
    return [_to_message(m) for m in raw]


async def list_today(
    account: str = "default", max_results: int = DEFAULT_MAX_RESULTS
) -> list[GmailMessage]:
    creds = await _load_creds(account)
    raw = await _run_google(_fetch_messages, creds, "newer_than:1d in:inbox", max_results)
    return [_to_message(m) for m in raw]


async def search(
    query: str, account: str = "default", max_results: int = DEFAULT_MAX_RESULTS
) -> list[GmailMessage]:
    creds = await _load_creds(account)
    raw = await _run_google(_fetch_messages, creds, query, max_results)
    return [_to_message(m) for m in raw]


async def get_thread(thread_id: str, account: str = "default") -> list[GmailMessage]:
    creds = await _load_creds(account)
    raw = await _run_google(_fetch_thread, creds, thread_id)
    return _sorted_messages(raw)


async def list_recent_threads(
    account: str = "default",
    max_threads: int = MAX_THREADS_SCAN,
    window_days: int = RECENT_THREAD_WINDOW_DAYS,
) -> list[list[GmailMessage]]:
    creds = await _load_creds(account)
    query = f"newer_than:{window_days}d"
    raw_threads = await _run_google(_fetch_recent_threads, creds, query, max_threads)
    return [_sorted_messages(raw) for raw in raw_threads]
