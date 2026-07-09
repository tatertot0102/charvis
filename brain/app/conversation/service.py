"""Conversation service — the shared brain behind both /chat and Telegram.

Loads/creates a per-(channel, external_id) conversation, persists each turn, builds the
message list from history, and calls the LLM facade. No front-door details leak in here.
"""
from sqlalchemy import select

from app import llm
from app.config import get_settings
from app.conversation import context_handler, email_handler, intents, memory_handler
from app.db.models import Conversation, Message
from app.db.session import get_session
from app.integrations.google import calendar
from app.llm import ChatMessage
from app.security.crypto import EncryptionUnavailableError
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

        # Deterministic intents answer directly (no general model call). Phase 2A: calendar;
        # 2B: email; 2C: cross-source context/meeting-prep; 2C.5: memory introspection.
        # Memory is checked first: "why do you think X…" must not be swallowed by other matchers.
        memory_intent = intents.detect_memory_intent(text)
        context_intent = intents.detect_context_intent(text)
        email_intent = intents.detect_email_intent(text)
        if memory_intent is not None:
            reply = await memory_handler.handle(*memory_intent)
        elif intents.is_todays_schedule_query(text):
            reply = await _todays_schedule_reply()
        elif context_intent is not None:
            reply = await context_handler.handle(context_intent)
        elif email_intent is not None:
            reply = await email_handler.handle(*email_intent)
        else:
            history = await _load_recent_messages(session, conversation.id, settings.history_limit)
            prompt = [ChatMessage(role="system", content=settings.system_prompt)]
            prompt += [ChatMessage(role=m.role, content=m.content) for m in history]
            reply = await llm.generate(prompt)

        session.add(Message(conversation_id=conversation.id, role="assistant", content=reply))
        await session.commit()

    log.info("conversation_turn", channel=channel, conversation_id=conversation.id)
    return reply, conversation.id


async def _todays_schedule_reply() -> str:
    """Answer a 'what's my day?' query from the calendar, with friendly fallbacks."""
    try:
        events = await calendar.list_todays_events()
    except calendar.NotConnectedError:
        return (
            "I'm not connected to your Google Calendar yet. Ask me to connect (or hit "
            "/integrations/google/connect) to grant read-only access."
        )
    except EncryptionUnavailableError:
        return "I can't read your calendar yet — the encryption key isn't configured on the server."
    except Exception as exc:  # noqa: BLE001 — friendly message to the user, detail to the logs.
        log.error("schedule_reply_failed", error=str(exc), error_type=type(exc).__name__)
        return "Sorry — I couldn't reach your calendar just now. Try again in a moment."
    return calendar.format_todays_events(events)


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
