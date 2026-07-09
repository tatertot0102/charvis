"""Phase 2D adds the calendar WRITE scope to the shared Google OAuth flow (needs re-consent)."""
from app.integrations.google import oauth


def test_calendar_events_write_scope_present():
    assert oauth.CALENDAR_EVENTS_SCOPE in oauth.SCOPES
    assert any("calendar.events" in scope for scope in oauth.SCOPES)


def test_read_scopes_still_present():
    # Additive: adding the write scope must not drop the read scopes (2A/2B stay working).
    assert oauth.CALENDAR_READONLY_SCOPE in oauth.SCOPES
    assert oauth.GMAIL_READONLY_SCOPE in oauth.SCOPES
