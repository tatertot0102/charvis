"""Integration tests for the /memory/* endpoints (requires the test Postgres, migrated)."""
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.db.models import EmailMessage
from app.db.session import get_session
from app.main import app


def _auth() -> dict[str, str]:
    return {"Authorization": f"Bearer {get_settings().auth_shared_token}"}


async def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed_project_emails(token: str, n: int = 6) -> None:
    """Seed n distinct threads whose subject shares a distinctive token → a derivable project.

    IDs are randomized per run so the shared test Postgres (a persistent volume) doesn't collide.
    """
    now = datetime.now(UTC) - timedelta(days=1)
    run = uuid4().hex[:8]
    async with get_session() as session:
        for i in range(n):
            session.add(
                EmailMessage(
                    account="default", gmail_id=f"{token}-{run}-{i}",
                    thread_id=f"{token}-thread-{run}-{i}",
                    from_email="lab@school.edu", from_name="Lab", to_emails="me@example.com",
                    subject=f"{token} experiment update {i}", snippet="progress",
                    received_at=now, labels="INBOX", direction="inbound",
                    importance="normal", urgency="normal",
                )
            )
        await session.commit()


async def test_memory_endpoints_require_auth():
    async with await _client() as client:
        for path in ("/memory/conclusions", "/memory/patterns", "/memory/projects",
                     "/memory/people", "/memory/commitments"):
            resp = await client.get(path)
            assert resp.status_code == 401, path


async def test_consolidate_then_project_appears():
    await _seed_project_emails("Zephyrus")
    async with await _client() as client:
        consolidate = await client.post("/memory/consolidate", headers=_auth())
        assert consolidate.status_code == 200
        assert consolidate.json()["conclusions"] >= 1

        projects = await client.get("/memory/projects", headers=_auth())
    body = projects.json()
    subjects = [c["subject"] for c in body["conclusions"]]
    assert "Zephyrus" in subjects  # display_name title-cases tokens longer than 5 chars
    project = next(c for c in body["conclusions"] if c["subject"] == "Zephyrus")
    # Every conclusion is auditable: confidence + evidence + sources travel with it.
    assert 0.0 < project["confidence"] <= 1.0
    assert project["evidence"]["by_source"].get("gmail", 0) >= 5
    assert "gmail" in project["source_list"]
    assert project["first_seen"] and project["last_updated"]


async def test_conclusions_confidence_filter():
    await _seed_project_emails("Borealis")
    async with await _client() as client:
        await client.post("/memory/consolidate", headers=_auth())
        resp = await client.get(
            "/memory/conclusions", headers=_auth(), params={"min_confidence": 0.99}
        )
    # Nothing is ever certain, so a 0.99 floor should return few/none — proves the filter works.
    for c in resp.json()["conclusions"]:
        assert c["confidence"] >= 0.99


async def test_commitments_endpoint_shape():
    async with await _client() as client:
        await client.post("/memory/consolidate", headers=_auth())
        resp = await client.get("/memory/commitments", headers=_auth())
    assert resp.status_code == 200
    assert "commitments" in resp.json()
