"""Fixtures for Gmail tests — build GmailMessage objects and raw Gmail API dicts. Not a test module."""
from __future__ import annotations

from datetime import UTC, datetime

from app.integrations.google.gmail import GmailMessage

MY_EMAIL = "me@example.com"


def msg(
    *,
    gmail_id: str = "m1",
    thread_id: str = "t1",
    from_email: str = "alice@example.com",
    from_name: str | None = "Alice",
    to: tuple[str, ...] = (MY_EMAIL,),
    subject: str = "Hi",
    snippet: str = "hello",
    received_at: datetime | None = None,
    labels: tuple[str, ...] = ("INBOX",),
) -> GmailMessage:
    return GmailMessage(
        gmail_id=gmail_id,
        thread_id=thread_id,
        from_email=from_email,
        from_name=from_name,
        to_emails=tuple(to),
        subject=subject,
        snippet=snippet,
        received_at=received_at or datetime(2026, 7, 7, 12, 0, tzinfo=UTC),
        labels=tuple(labels),
    )


def raw(
    *,
    id: str = "m1",
    thread_id: str = "t1",
    from_: str = "Alice Smith <alice@example.com>",
    to: str = MY_EMAIL,
    subject: str = "Hi",
    snippet: str = "hello",
    date: str = "Mon, 07 Jul 2026 12:00:00 +0000",
    labels: tuple[str, ...] = ("INBOX",),
) -> dict:
    return {
        "id": id,
        "threadId": thread_id,
        "snippet": snippet,
        "labelIds": list(labels),
        "payload": {
            "headers": [
                {"name": "From", "value": from_},
                {"name": "To", "value": to},
                {"name": "Subject", "value": subject},
                {"name": "Date", "value": date},
            ]
        },
    }
