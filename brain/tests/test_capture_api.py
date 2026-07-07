"""/capture stores a note and enforces auth. Requires DB (run via `make test`)."""
from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.main import app


async def test_capture_requires_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/capture", json={"text": "buy milk"})
    assert response.status_code == 401


async def test_capture_stores_note():
    token = get_settings().auth_shared_token
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/capture",
            json={"text": "essay due Friday"},
            headers={"Authorization": f"Bearer {token}"},
        )
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "captured"
    assert isinstance(body["id"], int)
