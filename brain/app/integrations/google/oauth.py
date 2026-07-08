"""Google OAuth 2.0 flow (Phase 2A) — read-only Calendar scope only.

Two-step web flow:
  1. build_auth_url() → the URL the operator opens in a browser to grant consent.
  2. exchange_code(code, state) → Google redirects back with a code; we swap it for tokens and
     store them encrypted (app.integrations.google.tokens).

No write scopes are ever requested here (MVP.md: read-only). Adding gmail.send etc. is a Phase 4
concern that must go through the autonomy gate.
"""
from __future__ import annotations

import asyncio

from google_auth_oauthlib.flow import Flow

from app.config import Settings, get_settings
from app.integrations.google import tokens
from app.telemetry import get_logger

log = get_logger(__name__)

CALENDAR_READONLY_SCOPE = "https://www.googleapis.com/auth/calendar.readonly"
SCOPES = [CALENDAR_READONLY_SCOPE]

_AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
_TOKEN_URI = "https://oauth2.googleapis.com/token"

# In-memory CSRF state store. This is a single-user, single-worker service: a pending OAuth `state`
# lives only for the seconds between /connect and /callback. It is deliberately NOT persisted (no
# second table for a transient nonce) — a restart mid-flow just means re-running /connect.
_pending_states: set[str] = set()


class GoogleOAuthNotConfiguredError(RuntimeError):
    """Raised when GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set."""


class InvalidOAuthStateError(RuntimeError):
    """Raised on callback when the `state` does not match a pending flow (CSRF guard)."""


def _require_config(settings: Settings) -> None:
    if not settings.google_client_id or not settings.google_client_secret:
        raise GoogleOAuthNotConfiguredError(
            "GOOGLE_CLIENT_ID / GOOGLE_CLIENT_SECRET are not set. "
            "Complete the Google Cloud setup in EXTERNAL_ACTIONS.md §2 and add them to .env."
        )


def _client_config(settings: Settings) -> dict:
    return {
        "web": {
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret,
            "auth_uri": _AUTH_URI,
            "token_uri": _TOKEN_URI,
            "redirect_uris": [settings.google_oauth_redirect_uri],
        }
    }


def _flow(settings: Settings, state: str | None = None) -> Flow:
    return Flow.from_client_config(
        _client_config(settings),
        scopes=SCOPES,
        redirect_uri=settings.google_oauth_redirect_uri,
        state=state,
    )


def build_auth_url() -> str:
    """Return the Google consent URL and remember its CSRF state. Offline access → refresh token."""
    settings = get_settings()
    _require_config(settings)
    flow = _flow(settings)
    auth_url, state = flow.authorization_url(
        access_type="offline",  # ask for a refresh token
        include_granted_scopes="true",  # incremental auth
        prompt="consent",  # force a refresh token even on re-auth
    )
    _pending_states.add(state)
    log.info("google_oauth_url_built")
    return auth_url


async def exchange_code(code: str, state: str, account: str = "default") -> None:
    """Verify state, exchange the auth code for tokens, and store them encrypted."""
    settings = get_settings()
    _require_config(settings)
    if state not in _pending_states:
        raise InvalidOAuthStateError("Unknown or expired OAuth state.")
    _pending_states.discard(state)

    flow = _flow(settings, state=state)
    # fetch_token performs a blocking token-endpoint request → keep it off the event loop.
    await asyncio.to_thread(flow.fetch_token, code=code)
    await tokens.save_credentials(flow.credentials, account=account)
    log.info("google_oauth_exchanged", account=account)
