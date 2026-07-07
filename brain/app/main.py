"""FastAPI entrypoint. Phase 0: mounts /health only."""
from fastapi import FastAPI

from app.api.health import router as health_router
from app.config import get_settings
from app.telemetry import configure_logging, get_logger

configure_logging()
log = get_logger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Jarvis Brain", version="0.0.0")
    app.include_router(health_router)
    log.info("brain_started", app_env=settings.app_env)
    return app


app = create_app()
