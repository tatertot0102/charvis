"""Canonical entity + permanent alias resolution (Phase 2D.3 integration).

"ARISE", "DSI", "Machine Learning Lab", "ECE Machine Learning Lab" must collapse to ONE entity;
"LuAnn", "LuAnn Williams", "Dr Williams" to ONE person. Corrections the user makes ("it is ECE
Machine Learning Lab") store an alias FOREVER so every future search resolves automatically. This is
the memory that makes cross-provider merging coherent — providers match facts against an entity's full
alias set, not just the exact words the user typed.
"""
from __future__ import annotations

import re

from sqlalchemy import select

from app.db.models import EntityAlias, KnowledgeEntity
from app.db.session import get_session
from app.knowledge.model import EntityRef

_STRIP_PUNCT = re.compile(r"[^a-z0-9\s]")
# Tokens too generic to be a useful match term on their own — a bare "with" or "the" as a match term
# causes false positives (e.g. matching a calendar event's description). Function words + a few
# domain-generic nouns.
_STOPWORDS = frozenset({
    "the", "a", "an", "my", "your", "our", "of", "for", "to", "on", "in", "at", "by", "with",
    "and", "or", "but", "is", "are", "was", "were", "be", "am", "do", "does", "did", "this",
    "that", "these", "those", "it", "its", "as", "from", "about", "into", "you", "me", "we",
    "us", "they", "them", "up", "out", "off", "so", "if", "any", "all", "new", "get", "got",
    "lab", "meeting", "event", "class", "session", "appointment", "dr", "mr", "mrs", "ms",
})


def normalize(name: str) -> str:
    return " ".join(_STRIP_PUNCT.sub("", (name or "").lower()).split())


def significant_tokens(name: str) -> list[str]:
    return [t for t in normalize(name).split() if t not in _STOPWORDS]


async def upsert_entity(
    session, canonical_name: str, entity_type: str, account: str = "default"
) -> KnowledgeEntity:
    """Get or create the canonical entity for (account, type, normalized_name)."""
    norm = normalize(canonical_name)
    row = (
        await session.execute(
            select(KnowledgeEntity).where(
                KnowledgeEntity.account == account,
                KnowledgeEntity.entity_type == entity_type,
                KnowledgeEntity.normalized_name == norm,
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = KnowledgeEntity(
            account=account, entity_type=entity_type,
            canonical_name=canonical_name, normalized_name=norm,
        )
        session.add(row)
        await session.flush()
    return row


async def add_alias(
    session, entity_id: int, alias: str, *, alias_type: str | None = None,
    source_type: str = "conversation", confidence: float = 0.9, account: str = "default",
) -> None:
    """Attach an alias to an entity (idempotent on normalized_alias)."""
    norm = normalize(alias)
    if not norm:
        return
    existing = (
        await session.execute(
            select(EntityAlias).where(
                EntityAlias.account == account,
                EntityAlias.entity_id == entity_id,
                EntityAlias.normalized_alias == norm,
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        if confidence > existing.confidence:
            existing.confidence = confidence
        return
    session.add(
        EntityAlias(
            account=account, entity_id=entity_id, alias=alias, normalized_alias=norm,
            alias_type=alias_type, source_type=source_type, confidence=confidence,
        )
    )


async def _load_aliases(session, entity_id: int, account: str) -> list[str]:
    rows = (
        await session.execute(
            select(EntityAlias.alias).where(
                EntityAlias.account == account, EntityAlias.entity_id == entity_id
            )
        )
    ).scalars().all()
    return list(rows)


async def resolve_name(name: str, account: str = "default") -> EntityRef | None:
    """Resolve a mention to its canonical entity (via alias or canonical name), or None if unknown."""
    norm = normalize(name)
    if not norm:
        return None
    async with get_session() as session:
        alias = (
            await session.execute(
                select(EntityAlias).where(
                    EntityAlias.account == account, EntityAlias.normalized_alias == norm
                )
            )
        ).scalar_one_or_none()
        entity_id = alias.entity_id if alias is not None else None
        if entity_id is None:
            entity = (
                await session.execute(
                    select(KnowledgeEntity).where(
                        KnowledgeEntity.account == account,
                        KnowledgeEntity.normalized_name == norm,
                    )
                )
            ).scalar_one_or_none()
            if entity is None:
                return None
            entity_id = entity.id
        else:
            entity = await session.get(KnowledgeEntity, entity_id)
            if entity is None:
                return None
        aliases = await _load_aliases(session, entity_id, account)
        return EntityRef(
            canonical_name=entity.canonical_name,
            entity_type=entity.entity_type,
            aliases=tuple(aliases),
            entity_id=entity_id,
        )


async def record_correction(
    old_name: str, new_name: str, *, entity_type: str = "commitment", account: str = "default"
) -> EntityRef:
    """Persist "it is <new_name>" — canonicalize new_name and alias old_name (and prior aliases) to it.

    Permanent: future queries for the old name resolve to the corrected entity forever (behaviors 7/8).
    """
    async with get_session() as session:
        entity = await upsert_entity(session, new_name, entity_type, account)
        # If old_name already resolved to a different entity, carry its aliases over.
        old_norm = normalize(old_name)
        if old_norm and old_norm != entity.normalized_name:
            prior = (
                await session.execute(
                    select(EntityAlias).where(
                        EntityAlias.account == account, EntityAlias.normalized_alias == old_norm
                    )
                )
            ).scalar_one_or_none()
            if prior is not None and prior.entity_id != entity.id:
                for carried in await _load_aliases(session, prior.entity_id, account):
                    await add_alias(session, entity.id, carried, alias_type="carried", account=account)
            await add_alias(session, entity.id, old_name, alias_type="correction", account=account)
        await add_alias(session, entity.id, new_name, alias_type="canonical", account=account)
        aliases = await _load_aliases(session, entity.id, account)
        ref = EntityRef(
            canonical_name=entity.canonical_name, entity_type=entity.entity_type,
            aliases=tuple(aliases), entity_id=entity.id,
        )
        await session.commit()
    return ref


def match_terms(name: str, ref: EntityRef | None) -> list[str]:
    """Lowercased substrings a provider matches a fact against.

    Includes the full normalized name and every alias (so "DSI" and "Data Science Institute" both
    match), PLUS their significant tokens (so a multi-word entity still matches a partial mention —
    "ECE Machine Learning Lab" matches an event titled "ECE ML"). Broad on purpose: merging should
    over-include and let reality labels sort it out, rather than miss a real connection.
    """
    phrases = {normalize(name)} if name else set()
    if ref is not None:
        phrases.add(normalize(ref.canonical_name))
        phrases.update(normalize(a) for a in ref.aliases)
    terms = {p for p in phrases if p}
    for phrase in list(phrases):
        for token in phrase.split():
            if token not in _STOPWORDS and len(token) > 2:
                terms.add(token)
    return list(terms)
