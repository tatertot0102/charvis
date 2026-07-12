"""Read-only Life Model API (Phase 2D.4): graph, entity neighborhood, routines. Token-gated."""
from datetime import UTC, datetime

from httpx import ASGITransport, AsyncClient

from app.config import get_settings
from app.lifemodel import graph
from app.main import app
from app.memory.schema import DerivedConclusion, Evidence, MemorySet, SourceRef

ACCOUNT = "test_lm_api"


def _auth():
    return {"Authorization": f"Bearer {get_settings().auth_shared_token}"}


async def _client():
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _seed():
    from app.lifemodel import build

    shared = SourceRef("gmail", "th1", "email: ARISE", datetime(2026, 6, 1, tzinfo=UTC))
    project = DerivedConclusion(
        kind="project", subject="ARISE", statement="“ARISE” is an active project.",
        confidence=0.9, evidence=_ev(shared), contexts=("Research",),
    )
    person = DerivedConclusion(
        kind="person", subject="luann@x.edu", statement="LuAnn is an important contact.",
        confidence=0.8, evidence=_ev(shared), display_name="LuAnn Williams",
    )
    await build.rebuild(MemorySet(conclusions=(project, person)), ACCOUNT)


def _ev(*refs: SourceRef) -> Evidence:
    e = Evidence()
    for r in refs:
        e.add(r)
    return e


async def test_graph_requires_auth():
    async with await _client() as c:
        resp = await c.get("/lifemodel/graph", params={"account": ACCOUNT})
    assert resp.status_code == 401


async def test_graph_returns_nodes_and_edges():
    await _seed()
    async with await _client() as c:
        resp = await c.get("/lifemodel/graph", headers=_auth(), params={"account": ACCOUNT})
    assert resp.status_code == 200
    body = resp.json()
    names = {n["canonical_name"] for n in body["nodes"]}
    assert {"ARISE", "LuAnn Williams"} <= names
    assert any(e["relation_type"] == "works_on" for e in body["edges"])


async def test_entity_neighborhood_endpoint():
    await _seed()
    ref = await graph.neighborhood_for_name(ACCOUNT, "ARISE")
    async with await _client() as c:
        resp = await c.get(
            f"/lifemodel/entity/project/{ref['id']}", headers=_auth(),
            params={"account": ACCOUNT},
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["canonical_name"] == "ARISE"
    assert body["inferred_role"] == "Research"
    assert any(f["predicate"] == "summary" for f in body["facts"])


async def test_entity_wrong_type_is_404():
    await _seed()
    ref = await graph.neighborhood_for_name(ACCOUNT, "ARISE")
    async with await _client() as c:
        resp = await c.get(
            f"/lifemodel/entity/person/{ref['id']}", headers=_auth(),
            params={"account": ACCOUNT},
        )
    assert resp.status_code == 404


async def test_routines_endpoint_shape():
    async with await _client() as c:
        resp = await c.get("/lifemodel/routines", headers=_auth(), params={"account": ACCOUNT})
    assert resp.status_code == 200
    assert "routines" in resp.json()
