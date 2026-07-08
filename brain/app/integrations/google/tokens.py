"""Encrypted persistence for Google OAuth credentials (Phase 2A).

Tokens are Fernet-encrypted at rest (app.security.crypto). This module is the only place that
reads/writes the `oauth_tokens` table for Google, and the only place that decrypts a token or
refreshes an expired access token. Refreshing persists the new access token transparently.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from sqlalchemy import select

from app.config import get_settings
from app.db.models import OAuthToken
from app.db.session import get_session
from app.security.crypto import decrypt, encrypt
from app.telemetry import get_logger

log = get_logger(__name__)

PROVIDER = "google"
_TOKEN_URI = "https://oauth2.googleapis.com/token"


def _to_aware_utc(naive_or_aware: datetime | None) -> datetime | None:
    """Store expiry as timezone-aware UTC (google-auth hands us naive UTC)."""
    if naive_or_aware is None:
        return None
    if naive_or_aware.tzinfo is None:
        return naive_or_aware.replace(tzinfo=UTC)
    return naive_or_aware.astimezone(UTC)


def _to_naive_utc(aware: datetime | None) -> datetime | None:
    """google-auth compares expiry against a naive UTC now(); hand it naive UTC."""
    if aware is None:
        return None
    if aware.tzinfo is None:
        return aware
    return aware.astimezone(UTC).replace(tzinfo=None)


async def is_connected(account: str = "default") -> bool:
    """True when a stored Google credential exists for this account."""
    async with get_session() as session:
        result = await session.execute(
            select(OAuthToken.id).where(
                OAuthToken.provider == PROVIDER, OAuthToken.account == account
            )
        )
        return result.scalar_one_or_none() is not None


async def save_credentials(creds: Credentials, account: str = "default") -> None:
    """Upsert encrypted Google credentials for `account` (one row per provider+account)."""
    scopes = " ".join(creds.scopes or [])
    access_enc = encrypt(creds.token)
    refresh_enc = encrypt(creds.refresh_token) if creds.refresh_token else None
    expiry = _to_aware_utc(creds.expiry)
    token_uri = creds.token_uri or _TOKEN_URI

    async with get_session() as session:
        result = await session.execute(
            select(OAuthToken).where(
                OAuthToken.provider == PROVIDER, OAuthToken.account == account
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            row = OAuthToken(provider=PROVIDER, account=account)
            session.add(row)
        row.scopes = scopes
        row.access_token_encrypted = access_enc
        # Google only returns a refresh_token on first consent; never clobber a stored one with None.
        if refresh_enc is not None:
            row.refresh_token_encrypted = refresh_enc
        row.token_uri = token_uri
        row.expiry = expiry
        await session.commit()
    log.info("google_token_saved", account=account, has_refresh=refresh_enc is not None)


async def load_credentials(account: str = "default") -> Credentials | None:
    """Load, decrypt, and (if expired) refresh Google credentials. None when not connected."""
    settings = get_settings()
    async with get_session() as session:
        result = await session.execute(
            select(OAuthToken).where(
                OAuthToken.provider == PROVIDER, OAuthToken.account == account
            )
        )
        row = result.scalar_one_or_none()
    if row is None:
        return None

    creds = Credentials(
        token=decrypt(row.access_token_encrypted),
        refresh_token=decrypt(row.refresh_token_encrypted) if row.refresh_token_encrypted else None,
        token_uri=row.token_uri,
        client_id=settings.google_client_id,
        client_secret=settings.google_client_secret,
        scopes=row.scopes.split() if row.scopes else None,
    )
    creds.expiry = _to_naive_utc(row.expiry)

    if creds.expired and creds.refresh_token:
        await asyncio.to_thread(creds.refresh, Request())
        await save_credentials(creds, account=account)
        log.info("google_token_refreshed", account=account)

    return creds
