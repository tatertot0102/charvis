"""FastAPI entrypoint. Phase 1: /health, /chat, /capture, and the Telegram long-poller."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.approvals import router as approvals_router
from app.api.calendar import router as calendar_router
from app.api.capture import router as capture_router
from app.api.chat import router as chat_router
from app.api.gmail import router as gmail_router
from app.api.google_oauth import router as google_oauth_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.memory import router as memory_router
from app.api.state import router as state_router
from app.config import get_settings
from app.telemetry import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


async def _start_telegram(settings):
    """Start the Telegram poller if configured. Never lets a bot failure take down the API."""
    token = (settings.telegram_bot_token or "").strip()
    if not token:
        log.info("telegram_disabled_no_token")
        return None

    log.info("telegram_enabled", allowed_user_count=len(settings.telegram_allowed_ids))
    try:
        # Imported lazily so the app runs without python-telegram-bot config in tests.
        from app.comms.telegram import TelegramChannel

        channel = TelegramChannel(token, settings.telegram_allowed_ids)
        await channel.start()
    except Exception as exc:  # noqa: BLE001 — log clearly, keep the API serving.
        log.error("telegram_start_failed", error=str(exc), error_type=type(exc).__name__)
        return None

    log.info("telegram_started")
    return channel


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop the Telegram poller alongside the API (only if a token is configured)."""
    settings = get_settings()
    app.state.telegram = await _start_telegram(settings)
    try:
        yield
    finally:
        channel = app.state.telegram
        if channel is not None:
            try:
                await channel.stop()
                log.info("telegram_stopped")
            except Exception as exc:  # noqa: BLE001
                log.error("telegram_stop_failed", error=str(exc))


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Jarvis Brain", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(capture_router)
    app.include_router(google_oauth_router)
    app.include_router(calendar_router)
    app.include_router(gmail_router)
    app.include_router(state_router)
    app.include_router(memory_router)
    app.include_router(approvals_router)
    app.include_router(knowledge_router)
    log.info("brain_started", app_env=settings.app_env, llm_provider=settings.local_llm_provider)
    return app


app = create_app()
