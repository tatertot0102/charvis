"""Per-conversation active-task memory (Phase 2D.3) — the cure for lost continuity.

Root-cause defect R2: "Check my email for upcoming events." → "LuAnn." → "LuAnn Williams." arrived as
three unrelated messages, so the bare names matched no intent and fell to the raw LLM, which denied a
capability it has. This module records the ACTIVE task for a conversation and decides whether the next
short message is a refinement of it (re-scope the same search) or a brand-new request.

State is written within the conversation turn's own session and expires after a short window so a name
typed an hour later never silently re-triggers an old search.
"""
from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.db.models import ConversationTaskState

DEFAULT_TTL_MINUTES = 30

_STRIP_PUNCT = re.compile(r"[^a-z0-9\s]")

# A leading word that makes a short message a fresh question, not a refinement of the active task.
_QUESTION_WORDS = frozenset(
    {
        "what", "whats", "who", "whos", "when", "where", "why", "how",
        "is", "are", "was", "were", "do", "does", "did", "can", "could",
        "will", "would", "should", "show", "list", "tell", "check", "find",
    }
)
# Tokens that carry no reference on their own — a message made only of these isn't a refinement.
_FILLERS = frozenset(
    {
        "hi", "hello", "hey", "thanks", "thank", "you", "ok", "okay", "yes", "no", "yeah",
        "nope", "yep", "sure", "cool", "nice", "great", "please", "the", "a", "an", "it",
    }
)


def _normalize(text: str) -> str:
    return " ".join(_STRIP_PUNCT.sub("", text.lower()).split())


def looks_like_bare_reference(text: str) -> bool:
    """True when a short message reads as a refinement (a name/fragment), not a new question.

    Used only after every deterministic intent has already declined the message, so this decides
    between "re-scope the active task" and "hand to the general model".
    """
    tokens = _normalize(text).split()
    if not tokens or len(tokens) > 5:
        return False
    if tokens[0] in _QUESTION_WORDS:
        return False
    if all(t in _FILLERS for t in tokens):
        return False
    return True


async def get_active(
    session, conversation_id: int, *, now: datetime | None = None
) -> ConversationTaskState | None:
    """Return the conversation's active task if one exists and hasn't expired, else None."""
    now = now or datetime.now(UTC)
    row = (
        await session.execute(
            select(ConversationTaskState).where(
                ConversationTaskState.conversation_id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        return None
    if row.expires_at is not None and row.expires_at <= now:
        return None
    return row


async def remember(
    session,
    conversation_id: int,
    *,
    intent: str | None,
    source_types: list[str] | tuple[str, ...] = (),
    time_range: dict | None = None,
    query: str | None = None,
    person_name: str | None = None,
    entity_id: int | None = None,
    unresolved_reference: str | None = None,
    ttl_minutes: int = DEFAULT_TTL_MINUTES,
    now: datetime | None = None,
) -> ConversationTaskState:
    """Upsert the single active-task row for a conversation (one row per conversation)."""
    now = now or datetime.now(UTC)
    expires = now + timedelta(minutes=ttl_minutes)
    row = (
        await session.execute(
            select(ConversationTaskState).where(
                ConversationTaskState.conversation_id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        row = ConversationTaskState(conversation_id=conversation_id)
        session.add(row)
    row.active_intent = intent
    row.active_entity_id = entity_id
    row.active_person_name = person_name
    row.active_source_types = list(source_types)
    row.active_time_range = time_range or {}
    row.active_query = query
    row.unresolved_reference = unresolved_reference
    row.expires_at = expires
    await session.flush()
    return row


async def clear(session, conversation_id: int) -> None:
    """Drop the active task (e.g. the user asked something unrelated and resolved)."""
    row = (
        await session.execute(
            select(ConversationTaskState).where(
                ConversationTaskState.conversation_id == conversation_id
            )
        )
    ).scalar_one_or_none()
    if row is not None:
        await session.delete(row)
        await session.flush()
