"""FastAPI entrypoint. Mounts the API routers, the Telegram long-poller, and the dashboard SPA."""
import json
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.api.approvals import router as approvals_router
from app.api.calendar import router as calendar_router
from app.api.capture import router as capture_router
from app.api.chat import router as chat_router
from app.api.dashboard import router as dashboard_router
from app.api.gmail import router as gmail_router
from app.api.google_oauth import router as google_oauth_router
from app.api.health import router as health_router
from app.api.knowledge import router as knowledge_router
from app.api.memory import router as memory_router
from app.api.state import router as state_router
from app.config import get_settings
from app.telemetry import configure_logging, get_logger

# The built dashboard SPA (produced by the Docker frontend stage into /app/dashboard_dist).
_DIST = Path(__file__).resolve().parent.parent / "dashboard_dist"

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
    app.include_router(dashboard_router)
    _mount_spa(app, settings)
    log.info("brain_started", app_env=settings.app_env, llm_provider=settings.local_llm_provider)
    return app


def _mount_spa(app: FastAPI, settings) -> None:
    """Serve the built dashboard SPA same-origin, so it reaches the token-gated API without CORS.

    The shared token is injected into the served HTML so the single-user, Tailscale-only dashboard can
    authenticate. This is acceptable for a private single-user deployment (Tailscale is the perimeter,
    the whole API is behind this one token); a multi-user build would switch to session auth instead.
    The SPA catch-all is registered LAST, so every real API route is matched before it.
    """
    if not _DIST.exists():
        log.info("dashboard_spa_not_built", path=str(_DIST))
        return

    assets = _DIST / "assets"
    if assets.exists():
        app.mount("/assets", StaticFiles(directory=str(assets)), name="assets")

    index_path = _DIST / "index.html"
    html = index_path.read_text(encoding="utf-8") if index_path.exists() else "<h1>Dashboard</h1>"
    token_script = f"<script>window.__JARVIS_TOKEN__={json.dumps(settings.auth_shared_token)};</script>"
    injected = html.replace("</head>", f"{token_script}</head>")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def _spa_root() -> HTMLResponse:
        return HTMLResponse(injected)

    @app.get("/{full_path:path}", response_class=HTMLResponse, include_in_schema=False)
    async def _spa_fallback(full_path: str) -> HTMLResponse:
        # Client-side routes (/memory, /people/:id, …) all resolve to the SPA; API routes are
        # already matched above, so only genuine app paths reach here.
        return HTMLResponse(injected)


app = create_app()
