"""Phase 0 smoke test: the health endpoint enforces auth and reports status.

Run inside the brain container (the db service must be up) via `make test`.
"""
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def test_health_requires_auth() -> None:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")
    assert response.status_code == 401


async def test_health_ok_with_token() -> None:
    token = get_settings().auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    # DB is reachable when run via `make test` (compose db is healthy).
    assert body["database"] == "connected"
