"""Telegram front door — long-polling (no public port). Delegates to the conversation service."""
from telegram import Update
from telegram.ext import (
    Application,
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from app.capture import create_capture
from app.conversation import service
from app.integrations.google import oauth
from app.telemetry import get_logger

log = get_logger(__name__)

_START_TEXT = (
    "Jarvis here. Ask “what's my day?” (or /day), use /capture <note> to file a quick "
    "thought, or /connect_google to link your calendar (read-only)."
)


class TelegramChannel:
    """Runs a python-telegram-bot Application embedded in the app's event loop."""

    def __init__(self, token: str, allowed_ids: set[int]) -> None:
        self._allowed = allowed_ids
        self._app: Application = ApplicationBuilder().token(token).build()
        self._app.add_handler(CommandHandler("start", self._on_start))
        self._app.add_handler(CommandHandler("capture", self._on_capture))
        self._app.add_handler(CommandHandler("day", self._on_day))
        self._app.add_handler(CommandHandler("connect_google", self._on_connect_google))
        self._app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self._on_message))
        self._app.add_error_handler(self._on_error)

    async def start(self) -> None:
        await self._app.initialize()
        await self._app.start()
        await self._app.updater.start_polling(drop_pending_updates=True)

    async def stop(self) -> None:
        if self._app.updater and self._app.updater.running:
            await self._app.updater.stop()
        await self._app.stop()
        await self._app.shutdown()

    def _authorized(self, update: Update) -> bool:
        if not self._allowed:
            return True  # empty allow-list = allow all (dev convenience)
        user = update.effective_user
        return user is not None and user.id in self._allowed

    async def _on_message(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update) or update.message is None:
            return
        user_id = str(update.effective_user.id)
        try:
            reply, _cid = await service.handle_incoming("telegram", user_id, update.message.text)
        except Exception as exc:  # noqa: BLE001 — surface a friendly error, log the detail.
            log.error("telegram_handle_failed", error=str(exc))
            await update.message.reply_text("Sorry — I hit an error reaching the model.")
            return
        await update.message.reply_text(reply)

    async def _on_capture(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update) or update.message is None:
            return
        text = " ".join(context.args) if context.args else ""
        if not text.strip():
            await update.message.reply_text("Usage: /capture <thing to remember>")
            return
        capture_id = await create_capture(text, source="telegram")
        await update.message.reply_text(f"Captured ✓ (#{capture_id})")

    async def _on_day(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        """/day — same answer as the natural-language "what's my day?" query."""
        if not self._authorized(update) or update.message is None:
            return
        user_id = str(update.effective_user.id)
        try:
            reply, _cid = await service.handle_incoming("telegram", user_id, "what's my day?")
        except Exception as exc:  # noqa: BLE001 — friendly error, detail to logs.
            log.error("telegram_day_failed", error=str(exc))
            await update.message.reply_text("Sorry — I couldn't reach your calendar just now.")
            return
        await update.message.reply_text(reply)

    async def _on_connect_google(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update) or update.message is None:
            return
        try:
            auth_url = oauth.build_auth_url()
        except oauth.GoogleOAuthNotConfiguredError:
            await update.message.reply_text(
                "Google isn't configured on the server yet (missing client credentials)."
            )
            return
        except Exception as exc:  # noqa: BLE001 — surface a friendly error, log the detail.
            log.error("telegram_connect_google_failed", error=str(exc))
            await update.message.reply_text("Sorry — I couldn't start the Google connect flow.")
            return
        await update.message.reply_text(
            "Open this link to grant Jarvis read-only Calendar access, then come back and ask "
            f"“what's my day?”:\n\n{auth_url}"
        )

    async def _on_start(self, update: Update, _: ContextTypes.DEFAULT_TYPE) -> None:
        if not self._authorized(update) or update.message is None:
            return
        await update.message.reply_text(_START_TEXT)

    async def _on_error(self, _: object, context: ContextTypes.DEFAULT_TYPE) -> None:
        log.error("telegram_error", error=str(context.error))
