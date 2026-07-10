"""Live connectivity status for each data source, derived from real connection state.

Calendar and Gmail share one Google OAuth connection, so their baseline capability is the same: do we
hold refreshable credentials? Scope-level gaps (a Calendar-only token) surface when an actual read
raises NotConnectedError — handlers report that truthfully. This registry exists so nothing ever
claims "I can't see your email" while a working connection is present.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from google.auth.exceptions import GoogleAuthError

from app.integrations.google import tokens
from app.security.crypto import EncryptionUnavailableError
from app.telemetry import get_logger

log = get_logger(__name__)

CALENDAR = "calendar"
GMAIL = "gmail"


class SourceStatus(str, Enum):
    CONNECTED = "connected"
    DISCONNECTED = "disconnected"
    PERMISSION_MISSING = "permission_missing"
    TOKEN_EXPIRED = "token_expired"
    REQUEST_FAILED = "request_failed"
    UNAVAILABLE = "unavailable"  # server misconfig (e.g. no encryption key)


@dataclass(frozen=True)
class SourceReport:
    name: str
    status: SourceStatus
    detail: str

    @property
    def connected(self) -> bool:
        """True only when Jarvis can actually reach the source — the capability-truth flag."""
        return self.status == SourceStatus.CONNECTED


_UNREACHABLE = {
    SourceStatus.DISCONNECTED,
    SourceStatus.PERMISSION_MISSING,
    SourceStatus.TOKEN_EXPIRED,
    SourceStatus.UNAVAILABLE,
    SourceStatus.REQUEST_FAILED,
}


def status_from_exception(exc: BaseException) -> SourceStatus:
    """Map an exception a live read raised to a source status (so handlers can refine the baseline)."""
    from app.integrations.google import calendar as _cal
    from app.integrations.google import gmail as _gmail

    if isinstance(exc, EncryptionUnavailableError):
        return SourceStatus.UNAVAILABLE
    if isinstance(exc, GoogleAuthError):
        return SourceStatus.TOKEN_EXPIRED
    if isinstance(exc, (_cal.NotConnectedError, _gmail.NotConnectedError)):
        # Not-connected can mean "never connected" or "scope not granted"; both mean unreachable.
        return SourceStatus.DISCONNECTED
    return SourceStatus.REQUEST_FAILED


async def _google_credential_status(account: str) -> tuple[SourceStatus, str]:
    """The shared baseline: do we hold usable Google credentials for this account?"""
    try:
        creds = await tokens.load_credentials(account)
    except EncryptionUnavailableError:
        return SourceStatus.UNAVAILABLE, "the encryption key isn't configured on the server"
    except GoogleAuthError:
        return SourceStatus.TOKEN_EXPIRED, "Google wouldn't refresh the saved token"
    except Exception as exc:  # noqa: BLE001 — never let a status probe raise; report it.
        log.warning("source_status_probe_failed", account=account, error=str(exc))
        return SourceStatus.REQUEST_FAILED, "the connection check failed"
    if creds is None:
        return SourceStatus.DISCONNECTED, "Google isn't connected yet"
    return SourceStatus.CONNECTED, "Google is connected"


async def calendar_report(account: str = "default") -> SourceReport:
    status, detail = await _google_credential_status(account)
    return SourceReport(name=CALENDAR, status=status, detail=detail)


async def gmail_report(account: str = "default") -> SourceReport:
    status, detail = await _google_credential_status(account)
    return SourceReport(name=GMAIL, status=status, detail=detail)


async def all_reports(account: str = "default") -> dict[str, SourceReport]:
    """Every source's live status (both currently ride the same Google connection)."""
    status, detail = await _google_credential_status(account)
    return {
        CALENDAR: SourceReport(name=CALENDAR, status=status, detail=detail),
        GMAIL: SourceReport(name=GMAIL, status=status, detail=detail),
    }
