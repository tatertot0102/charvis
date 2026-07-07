"""Shared FastAPI dependencies. Phase 0: bearer-token auth on every endpoint."""
import secrets

from fastapi import Header, HTTPException, status

from app.config import get_settings


async def require_token(authorization: str | None = Header(default=None)) -> None:
    """Require `Authorization: Bearer <AUTH_SHARED_TOKEN>`.

    Uses a constant-time comparison to avoid leaking the token via timing. Designed to grow into
    multiple per-agent tokens later without changing call sites (see EXECUTION_PLAN §14.3).
    """
    settings = get_settings()
    expected = f"Bearer {settings.auth_shared_token}"
    if authorization is None or not secrets.compare_digest(authorization, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )
