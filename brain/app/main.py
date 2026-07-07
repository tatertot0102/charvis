"""FastAPI entrypoint. Phase 1: /health, /chat, /capture, and the Telegram long-poller."""
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api.capture import router as capture_router
from app.api.chat import router as chat_router
from app.api.health import router as health_router
from app.config import get_settings
from app.telemetry import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start/stop the Telegram poller alongside the API (only if a token is configured)."""
    settings = get_settings()
    channel = None
    if settings.telegram_bot_token:
        # Imported lazily so the app runs without python-telegram-bot config in tests.
        from app.comms.telegram import TelegramChannel

        channel = TelegramChannel(settings.telegram_bot_token, settings.telegram_allowed_ids)
        await channel.start()
        log.info("telegram_started")
    else:
        log.info("telegram_disabled_no_token")

    app.state.telegram = channel
    try:
        yield
    finally:
        if channel is not None:
            await channel.stop()
            log.info("telegram_stopped")


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Jarvis Brain", version="0.1.0", lifespan=lifespan)
    app.include_router(health_router)
    app.include_router(chat_router)
    app.include_router(capture_router)
    log.info("brain_started", app_env=settings.app_env, llm_provider=settings.local_llm_provider)
    return app


app = create_app()
