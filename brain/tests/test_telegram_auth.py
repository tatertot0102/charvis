"""Telegram allow-list logic — no network, no polling started."""
from types import SimpleNamespace

from app.comms.telegram import TelegramChannel

# A syntactically-valid dummy token; ApplicationBuilder().build() does not hit the network.
DUMMY_TOKEN = "123456:ABC-DEF"


def _update(user_id: int | None):
    user = SimpleNamespace(id=user_id) if user_id is not None else None
    return SimpleNamespace(effective_user=user)


def test_empty_allowlist_allows_all():
    channel = TelegramChannel(DUMMY_TOKEN, allowed_ids=set())
    assert channel._authorized(_update(999)) is True


def test_allowlist_permits_listed_user():
    channel = TelegramChannel(DUMMY_TOKEN, allowed_ids={42})
    assert channel._authorized(_update(42)) is True


def test_allowlist_blocks_unlisted_user():
    channel = TelegramChannel(DUMMY_TOKEN, allowed_ids={42})
    assert channel._authorized(_update(7)) is False


def test_missing_user_blocked_when_allowlist_set():
    channel = TelegramChannel(DUMMY_TOKEN, allowed_ids={42})
    assert channel._authorized(_update(None)) is False
