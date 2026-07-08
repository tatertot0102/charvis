"""Google OAuth endpoints (Phase 2A, read-only Calendar).

- GET /integrations/google/connect  (auth required) → returns the consent URL to open in a browser.
- GET /integrations/google/callback  (NO bearer auth — Google redirects a browser here) → exchanges
  the code for tokens. Protected against CSRF by the one-time `state` parameter.
"""
import html

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import HTMLResponse

from app.deps import require_token
from app.integrations.google import oauth
from app.schemas import GoogleConnectResponse
from app.telemetry import get_logger

log = get_logger(__name__)

router = APIRouter(prefix="/integrations/google", tags=["google"])


def _page(title: str, message: str, *, status_code: int = 200) -> HTMLResponse:
    """Minimal, self-contained success/error page (dynamic values HTML-escaped)."""
    body = (
        f"<!doctype html><html><head><meta charset='utf-8'><title>{html.escape(title)}</title>"
        "<meta name='viewport' content='width=device-width, initial-scale=1'>"
        "<style>body{font-family:system-ui,sans-serif;max-width:32rem;margin:4rem auto;"
        "padding:0 1rem;color:#1a1a1a}h1{font-size:1.4rem}p{color:#444}</style></head>"
        f"<body><h1>{html.escape(title)}</h1><p>{html.escape(message)}</p></body></html>"
    )
    return HTMLResponse(body, status_code=status_code)


@router.get("/connect", response_model=GoogleConnectResponse)
async def connect(_: None = Depends(require_token)) -> GoogleConnectResponse:
    """Return the Google consent URL. Open it in a browser and grant read-only Calendar access."""
    try:
        auth_url = oauth.build_auth_url()
    except oauth.GoogleOAuthNotConfiguredError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    return GoogleConnectResponse(auth_url=auth_url)


@router.get("/callback", response_class=HTMLResponse)
async def callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
) -> HTMLResponse:
    """Handle Google's redirect. Unauthenticated by necessity; CSRF-guarded by `state`."""
    if error:
        return _page("Authorization failed", f"Google returned: {error}", status_code=400)
    if not code or not state:
        return _page(
            "Missing parameters",
            "Expected both ?code and ?state. Re-run the connect flow.",
            status_code=400,
        )
    try:
        await oauth.exchange_code(code, state)
    except oauth.InvalidOAuthStateError:
        return _page(
            "Invalid or expired link",
            "This authorization link is stale. Re-run /integrations/google/connect and try again.",
            status_code=400,
        )
    except oauth.GoogleOAuthNotConfiguredError as exc:
        return _page("Not configured", str(exc), status_code=503)
    except Exception as exc:  # noqa: BLE001 — surface a friendly page, log the detail.
        log.error("google_oauth_callback_failed", error=str(exc))
        return _page(
            "Connection failed",
            "Google rejected the authorization exchange. Re-run /integrations/google/connect "
            "and try again.",
            status_code=502,
        )
    return _page(
        "Connected ✓",
        "Jarvis can now read your Google Calendar. You can close this tab and text “what's my "
        "day?”.",
    )
