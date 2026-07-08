"""The /day command reuses the shared 'what's my day?' pipeline (no network)."""
from types import SimpleNamespace

from app.comms import telegram as telegram_mod
from app.comms.telegram import TelegramChannel

DUMMY_TOKEN = "123456:ABC-DEF"


async def test_day_command_routes_to_schedule(monkeypatch):
    captured: dict[str, str] = {}

    async def fake_handle(channel: str, external_id: str, text: str):
        captured["text"] = text
        return ("Here's your day: nothing scheduled.", 1)

    monkeypatch.setattr(telegram_mod.service, "handle_incoming", fake_handle)

    channel = TelegramChannel(DUMMY_TOKEN, allowed_ids=set())
    sent: dict[str, str] = {}

    async def reply(text: str) -> None:
        sent["text"] = text

    message = SimpleNamespace(reply_text=reply, text="/day")
    update = SimpleNamespace(effective_user=SimpleNamespace(id=1), message=message)
    ctx = SimpleNamespace(args=[])

    await channel._on_day(update, ctx)

    assert "day" in captured["text"].lower()
    assert "your day" in sent["text"].lower()
