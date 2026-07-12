"""Life Model HTTP surface (Phase 2D.4) — the connected graph, exposed read-only.

The dashboard (and any future client) renders the Life Model through these endpoints; it never
reasons or reshapes — improving the reasoning/graph automatically improves what the dashboard shows.
All read-only and token-gated. No writes, no side effects.

- GET /lifemodel/graph                     → every node + edge for an account
- GET /lifemodel/entity/{type}/{id}        → one node's neighborhood (facts, edges, evidence, conflicts)
- GET /lifemodel/routines                  → detected weekday/weekly/monthly routines with evidence
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from app.deps import require_token
from app.lifemodel import graph
from app.memory import store as memory_store

router = APIRouter(tags=["lifemodel"])


@router.get("/lifemodel/graph")
async def lifemodel_graph(account: str = "default", _: None = Depends(require_token)) -> dict:
    """The whole life graph — nodes (with importance/role/evidence) and their typed edges."""
    return await graph.graph_snapshot(account)


@router.get("/lifemodel/entity/{entity_type}/{entity_id}")
async def lifemodel_entity(
    entity_type: str, entity_id: int, account: str = "default", _: None = Depends(require_token)
) -> dict:
    """One entity's neighborhood: inferred role/importance, facts+evidence, edges, open conflicts."""
    hood = await graph.neighborhood(account, entity_id)
    if hood is None or hood["entity_type"] != entity_type:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "entity not found")
    return hood


@router.get("/lifemodel/routines")
async def lifemodel_routines(account: str = "default", _: None = Depends(require_token)) -> dict:
    """Detected routines (weekday/weekly/monthly) with confidence, evidence counts, and sources."""
    patterns = await memory_store.list_patterns(account)
    routines = [
        {
            "subject": p.subject,
            "description": p.description,
            "confidence": p.confidence,
            "evidence": p.evidence.get("by_source", {}) if isinstance(p.evidence, dict) else {},
            "sources": p.source_list,
        }
        for p in patterns
        if p.pattern_type == "routine"
    ]
    return {"routines": routines}
