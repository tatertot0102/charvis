"""Unit tests for the live source-status registry (Phase 2D.3)."""
import pytest
from google.auth.exceptions import GoogleAuthError

from app.integrations.google import calendar as calendar_mod
from app.integrations.google import gmail as gmail_mod
from app.integrations.google import tokens
from app.security.crypto import EncryptionUnavailableError
from app.sources import registry
from app.sources.registry import SourceStatus


def _patch_creds(monkeypatch, *, result=None, raises=None):
    async def _load(account="default"):
        if raises is not None:
            raise raises
        return result

    monkeypatch.setattr(tokens, "load_credentials", _load)


async def test_connected_when_credentials_present(monkeypatch):
    _patch_creds(monkeypatch, result=object())
    report = await registry.calendar_report()
    assert report.status is SourceStatus.CONNECTED
    assert report.connected is True


async def test_disconnected_when_no_credentials(monkeypatch):
    _patch_creds(monkeypatch, result=None)
    report = await registry.gmail_report()
    assert report.status is SourceStatus.DISCONNECTED
    assert report.connected is False


async def test_unavailable_when_encryption_missing(monkeypatch):
    _patch_creds(monkeypatch, raises=EncryptionUnavailableError("no key"))
    report = await registry.calendar_report()
    assert report.status is SourceStatus.UNAVAILABLE
    assert report.connected is False


async def test_token_expired_on_auth_error(monkeypatch):
    _patch_creds(monkeypatch, raises=GoogleAuthError("refresh failed"))
    report = await registry.gmail_report()
    assert report.status is SourceStatus.TOKEN_EXPIRED


async def test_request_failed_on_unexpected_error(monkeypatch):
    _patch_creds(monkeypatch, raises=RuntimeError("boom"))
    report = await registry.calendar_report()
    assert report.status is SourceStatus.REQUEST_FAILED


async def test_all_reports_covers_both_sources(monkeypatch):
    _patch_creds(monkeypatch, result=object())
    reports = await registry.all_reports()
    assert reports[registry.CALENDAR].connected
    assert reports[registry.GMAIL].connected


@pytest.mark.parametrize(
    "exc, expected",
    [
        (EncryptionUnavailableError("x"), SourceStatus.UNAVAILABLE),
        (GoogleAuthError("x"), SourceStatus.TOKEN_EXPIRED),
        (calendar_mod.NotConnectedError("x"), SourceStatus.DISCONNECTED),
        (gmail_mod.NotConnectedError("x"), SourceStatus.DISCONNECTED),
        (ValueError("x"), SourceStatus.REQUEST_FAILED),
    ],
)
def test_status_from_exception(exc, expected):
    assert registry.status_from_exception(exc) is expected
