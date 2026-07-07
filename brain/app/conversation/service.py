"""Conversation service — the shared brain behind both /chat and Telegram.

Loads/creates a per-(channel, external_id) conversation, persists each turn, builds the
message list from history, and calls the LLM facade. No front-door details leak in here.
"""
from sqlalchemy import select

from app import llm
from app.config import get_settings
from app.db.models import Conversation, Message
from app.db.session import get_session
from app.llm import ChatMessage
from app.telemetry import get_logger

log = get_logger(__name__)


async def handle_incoming(channel: str, external_id: str, text: str) -> tuple[str, int]:
    """Process one inbound message; return (reply_text, conversation_id).

    History is persisted so the model sees prior turns on the next message.
    """
    settings = get_settings()
    async with get_session() as session:
        conversation = await _get_or_create_conversation(session, channel, external_id)

        session.add(Message(conversation_id=conversation.id, role="user", content=text))
        await session.flush()

        history = await _load_recent_messages(session, conversation.id, settings.history_limit)
        prompt = [ChatMessage(role="system", content=settings.system_prompt)]
        prompt += [ChatMessage(role=m.role, content=m.content) for m in history]

        reply = await llm.generate(prompt)

        session.add(Message(conversation_id=conversation.id, role="assistant", content=reply))
        await session.commit()

    log.info("conversation_turn", channel=channel, conversation_id=conversation.id)
    return reply, conversation.id


async def _get_or_create_conversation(session, channel: str, external_id: str) -> Conversation:
    result = await session.execute(
        select(Conversation).where(
            Conversation.channel == channel, Conversation.external_id == external_id
        )
    )
    conversation = result.scalar_one_or_none()
    if conversation is None:
        conversation = Conversation(channel=channel, external_id=external_id)
        session.add(conversation)
        await session.flush()
    return conversation


async def _load_recent_messages(session, conversation_id: int, limit: int) -> list[Message]:
    """Return the last `limit` messages in chronological order."""
    result = await session.execute(
        select(Message)
        .where(Message.conversation_id == conversation_id)
        .order_by(Message.id.desc())
        .limit(limit)
    )
    return list(reversed(result.scalars().all()))
