"""Google Calendar WRITE connector (Phase 2D) — create / move / delete events.

This is the only module that mutates Google Calendar. It is *dumb on purpose*: it takes a fully
resolved instruction and performs the API call. All policy — "may this run at all?" — lives upstream
in app.calendar_actions behind the confirmation gate. Nothing here decides to write; it only writes
what a confirmed pending action tells it to.

The Google client is synchronous, so every call is offloaded with asyncio.to_thread to keep the
event loop unblocked. Requires the calendar.events scope (see app.integrations.google.oauth); until
the operator re-consents, these calls raise WriteScopeError so the caller can explain why.
"""
from __future__ import annotations

import asyncio
from datetime import datetime

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from app.integrations.google import tokens
from app.integrations.google.calendar import NotConnectedError
from app.telemetry import get_logger

log = get_logger(__name__)

_PRIMARY_CALENDAR = "primary"


class WriteScopeError(RuntimeError):
    """Raised when the stored credential lacks calendar.events (operator must re-consent)."""


async def _write_credentials(account: str) -> Credentials:
    creds = await tokens.load_credentials(account)
    if creds is None:
        raise NotConnectedError("Google Calendar is not connected.")
    return creds


def _time_field(when: datetime) -> dict:
    """A Google event start/end node for a timed event (RFC 3339 with offset)."""
    return {"dateTime": when.isoformat()}


def _as_scope_error(exc: HttpError) -> bool:
    status = getattr(getattr(exc, "resp", None), "status", None)
    return status in (401, 403)


def _insert_event(creds: Credentials, body: dict) -> dict:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return service.events().insert(calendarId=_PRIMARY_CALENDAR, body=body).execute()


def _patch_event(creds: Credentials, event_id: str, body: dict) -> dict:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    return (
        service.events()
        .patch(calendarId=_PRIMARY_CALENDAR, eventId=event_id, body=body)
        .execute()
    )


def _delete_event(creds: Credentials, event_id: str) -> None:
    service = build("calendar", "v3", credentials=creds, cache_discovery=False)
    service.events().delete(calendarId=_PRIMARY_CALENDAR, eventId=event_id).execute()


async def create_event(
    *,
    summary: str,
    start: datetime,
    end: datetime,
    location: str | None = None,
    description: str | None = None,
    account: str = "default",
) -> dict:
    """Create a timed event. Returns the created event resource (id, htmlLink, …)."""
    creds = await _write_credentials(account)
    body: dict = {"summary": summary, "start": _time_field(start), "end": _time_field(end)}
    if location:
        body["location"] = location
    if description:
        body["description"] = description
    try:
        created = await asyncio.to_thread(_insert_event, creds, body)
    except HttpError as exc:
        if _as_scope_error(exc):
            raise WriteScopeError(str(exc)) from exc
        raise
    log.info("calendar_event_created", account=account, event_id=created.get("id"))
    return created


async def update_event(
    event_id: str,
    *,
    start: datetime | None = None,
    end: datetime | None = None,
    summary: str | None = None,
    location: str | None = None,
    account: str = "default",
) -> dict:
    """Patch an existing event (partial update — only the given fields change)."""
    creds = await _write_credentials(account)
    body: dict = {}
    if start is not None:
        body["start"] = _time_field(start)
    if end is not None:
        body["end"] = _time_field(end)
    if summary is not None:
        body["summary"] = summary
    if location is not None:
        body["location"] = location
    try:
        patched = await asyncio.to_thread(_patch_event, creds, event_id, body)
    except HttpError as exc:
        if _as_scope_error(exc):
            raise WriteScopeError(str(exc)) from exc
        raise
    log.info("calendar_event_updated", account=account, event_id=event_id)
    return patched


async def delete_event(event_id: str, account: str = "default") -> None:
    """Delete an event by id."""
    creds = await _write_credentials(account)
    try:
        await asyncio.to_thread(_delete_event, creds, event_id)
    except HttpError as exc:
        if _as_scope_error(exc):
            raise WriteScopeError(str(exc)) from exc
        raise
    log.info("calendar_event_deleted", account=account, event_id=event_id)
