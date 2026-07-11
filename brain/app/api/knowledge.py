"""Knowledge Engine HTTP surface (Phase 2D.3 integration).

The dashboard (and any future client) talks to the Knowledge Engine through these endpoints and
consumes the exact same WorldModel the conversation layer does — no business logic here, no direct
provider access. All read-only and token-gated.

- GET  /knowledge/sources          → live source status (the only capability truth)
- GET  /knowledge/entities         → canonical entities + aliases for an account
- POST /query                      → run knowledge.query(...) and return the serialized WorldModel
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select

from app import knowledge
from app.db.models import EntityAlias, KnowledgeEntity
from app.db.session import get_session
from app.deps import require_token
from app.sources import registry

router = APIRouter(tags=["knowledge"])


class QueryRequest(BaseModel):
    intent: str = "entity"  # schedule | entity | verify | email_events
    subjects: list[str] = Field(default_factory=list)
    person: str | None = None
    text: str = ""
    account: str = "default"
    days_back: int | None = None
    days_ahead: int | None = None
    minimum_confidence: float = 0.0


@router.post("/query")
async def run_query(req: QueryRequest, _: None = Depends(require_token)) -> dict:
    """Run the Knowledge Engine and return the merged WorldModel as JSON."""
    date_range = None
    if req.days_back is not None or req.days_ahead is not None:
        now = datetime.now(UTC)
        date_range = (
            now - timedelta(days=req.days_back or 0),
            now + timedelta(days=req.days_ahead or 0),
        )
    world = await knowledge.query(
        intent=req.intent,
        subjects=req.subjects,
        person=req.person,
        text=req.text or " ".join(req.subjects),
        date_range=date_range,
        account=req.account,
        minimum_confidence=req.minimum_confidence,
    )
    return world.to_dict()


@router.get("/knowledge/sources")
async def sources(account: str = "default", _: None = Depends(require_token)) -> dict:
    """Live connectivity status for every source — computed, never cached (capability truth)."""
    reports = await registry.all_reports(account)
    return {
        name: {"status": r.status.value, "connected": r.connected, "detail": r.detail}
        for name, r in reports.items()
    }


@router.get("/knowledge/entities")
async def entities(account: str = "default", _: None = Depends(require_token)) -> dict:
    """Canonical entities and their permanent aliases for an account."""
    async with get_session() as session:
        rows = (
            await session.execute(
                select(KnowledgeEntity).where(KnowledgeEntity.account == account)
            )
        ).scalars().all()
        out = []
        for entity in rows:
            aliases = (
                await session.execute(
                    select(EntityAlias.alias).where(EntityAlias.entity_id == entity.id)
                )
            ).scalars().all()
            out.append({
                "id": entity.id,
                "canonical_name": entity.canonical_name,
                "entity_type": entity.entity_type,
                "aliases": list(aliases),
            })
    return {"account": account, "entities": out}
