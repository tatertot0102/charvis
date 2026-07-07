"""Health endpoint — the only route in Phase 0. Token-protected; also reports DB reachability."""
from fastapi import APIRouter, Depends
from sqlalchemy import text

from app.db.session import get_session
from app.deps import require_token
from app.telemetry import get_logger

router = APIRouter()
log = get_logger(__name__)


@router.get("/health")
async def health(_: None = Depends(require_token)) -> dict[str, str]:
    """Return service status and whether Postgres is reachable.

    Always 200 when authorized (the point of Phase 0 is proving reachability). The `database`
    field distinguishes a live DB from a not-yet-ready one without failing the check.
    """
    database = "unavailable"
    try:
        async with get_session() as session:
            await session.execute(text("SELECT 1"))
            database = "connected"
    except Exception as exc:  # noqa: BLE001 — report, don't crash the health probe.
        log.warning("health_db_check_failed", error=str(exc))

    return {"status": "ok", "database": database}
