"""The shared Google OAuth flow must request the Gmail read-only scope in Phase 2B."""
from app.integrations.google import oauth


def test_gmail_readonly_scope_present():
    assert oauth.GMAIL_READONLY_SCOPE in oauth.SCOPES
    assert any("gmail.readonly" in scope for scope in oauth.SCOPES)


def test_calendar_scope_still_present():
    # Additive: adding Gmail must not drop Calendar (Phase 2A stays working).
    assert oauth.CALENDAR_READONLY_SCOPE in oauth.SCOPES
