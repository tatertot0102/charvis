"""Conversation service — the shared brain behind both /chat and Telegram.

Loads/creates a per-(channel, external_id) conversation, persists each turn, builds the
message list from history, and calls the LLM facade. No front-door details leak in here.
"""
from sqlalchemy import select

from app import llm
from app.config import get_settings
from app.calendar_state import schedule
from app.conversation import (
    calendar_handler,
    commitment_handler,
    context_handler,
    email_event_handler,
    email_handler,
    intents,
    knowledge_handler,
    life_handler,
    memory_handler,
    schedule_range_handler,
    task_state,
    verify_handler,
)
from app.db.models import Conversation, Message
from app.db.session import get_session
from app.integrations.google import calendar
from app.llm import ChatMessage
from app.query import ranges, validate
from app.security.crypto import EncryptionUnavailableError
from app.sources import registry
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
        # 2B: email; 2C: cross-source context/meeting-prep; 2C.5: memory introspection;
        # 2D: calendar-write confirmation flow; 2D.3: ranged schedule reads, calendar verification,
        # email event search, and cross-turn task continuity. An exact "CONFIRM"/"CANCEL" is checked
        # FIRST so it can never be swallowed by another matcher — it's the write gate. Memory is next.
        memory_intent = intents.detect_memory_intent(text)
        context_intent = intents.detect_context_intent(text)
        email_intent = intents.detect_email_intent(text)
        email_event = intents.detect_email_event_search(text)
        verify_intent = intents.detect_calendar_verification(text)
        schedule_range = intents.detect_schedule_range(text)
        entity_subject = intents.detect_entity_query(text)
        life_query = intents.detect_life_query(text)
        bulk_phrase = intents.bulk_confirm_phrase(text)
        if bulk_phrase is not None:
            # "CONFIRM DELETE"/"CONFIRM MOVE" — the stronger phrase a bulk action requires.
            reply = await calendar_handler.handle_confirm(phrase=bulk_phrase)
        elif intents.is_confirm(text):
            reply = await calendar_handler.handle_confirm(phrase="CONFIRM")
        elif intents.is_cancel(text):
            reply = await calendar_handler.handle_cancel()
        elif entity_subject is not None:
            # "what is ARISE / what is LuAnn related to / what do you know about X" — merge every
            # provider through the Knowledge Engine (Phase 2D.3). Checked before memory so a specific
            # subject isn't swallowed by the generic "what do you know about me" matcher.
            reply = await knowledge_handler.handle_entity(entity_subject)
            await task_state.remember(
                session, conversation.id, intent="entity_query",
                query=text, unresolved_reference=entity_subject,
            )
        elif life_query is not None:
            # "what should I focus on / what do I do every weekday" — reason over the whole life
            # model (priorities, routines, commitments), grounded, never a raw calendar dump.
            reply = await life_handler.handle(life_query)
        elif memory_intent is not None:
            reply = await memory_handler.handle(*memory_intent)
        elif email_event is not None:
            # "check my email for upcoming events" — a real Gmail event search, NOT list_unread (R3).
            _, person = email_event
            reply = await email_event_handler.handle(text, person=person)
            await task_state.remember(
                session, conversation.id, intent="email_event_search",
                source_types=["gmail"], query=text, person_name=person,
            )
        elif intents.is_todays_schedule_query(text):
            reply = await _todays_schedule_reply()
            await _remember_schedule(session, conversation.id, text, "today")
        elif intents.is_week_schedule_query(text):
            reply = await _week_schedule_reply()
            await _remember_schedule(session, conversation.id, text, "this_week")
        elif schedule_range is not None:
            # "what does my month/next week look like" — a ranged read from the real calendar (R1).
            reply = await schedule_range_handler.handle(text, schedule_range)
            await task_state.remember(
                session, conversation.id, intent="schedule_range",
                source_types=["calendar"], time_range=schedule_range.as_dict(), query=text,
            )
        elif verify_intent is not None:
            # "is X on my Google Calendar?" — verify against the provider, never guess (R4).
            _, subject = verify_intent
            subject = subject or await _resolve_reference(session, conversation.id)
            reply = await verify_handler.handle(subject)
            await task_state.remember(
                session, conversation.id, intent="calendar_verification",
                source_types=["calendar"], query=text, unresolved_reference=subject,
            )
        elif intents.is_free_time_query(text):
            reply = await calendar_handler.handle_free_time()
        elif context_intent is not None:
            reply = await context_handler.handle(context_intent)
        elif email_intent is not None:
            reply = await email_handler.handle(*email_intent)
        elif (
            calendar_reply := await calendar_handler.handle_request(
                text, channel=channel, external_id=external_id
            )
        ) is not None:
            # A create/move/cancel request → drafts a pending action (never a write) and returns the
            # proposal text. None means it wasn't a calendar action; fall through.
            reply = calendar_reply
        elif (
            commitment_reply := await commitment_handler.handle(
                text, account="default", channel=channel, external_id=external_id
            )
        ) is not None:
            # A commitment correction ("it is X") or recurrence statement ("it's every weekday 10–2").
            # Updates our memory and/or drafts a CONFIRM-gated recurring create — never a silent write.
            reply = commitment_reply
        elif (followup := await _handle_followup(session, conversation.id, text)) is not None:
            # A bare follow-up ("LuAnn", "this month") that refines the active task instead of
            # starting a new chat — the cure for lost continuity (R2).
            reply = followup
        else:
            history = await _load_recent_messages(session, conversation.id, settings.history_limit)
            prompt = [ChatMessage(role="system", content=settings.system_prompt)]
            prompt += [ChatMessage(role=m.role, content=m.content) for m in history]
            # THE TRUTH GUARD: this is the one branch where Jarvis took no action. A reply that invents
            # events, claims a write, or denies a connected capability is false — replace it. Source
            # truth comes from the live registry (Phase 2D.3), the only source of capability claims.
            reports = await registry.all_reports("default")
            reply = validate.sanitize_fallback(await llm.generate(prompt), reports=reports)

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


async def _week_schedule_reply(account: str = "default") -> str:
    """Answer a 'what's my week?' query from the snapshot cache — never the model (Phase 2D.2)."""
    try:
        return await schedule.week_summary(account)
    except calendar.NotConnectedError:
        return (
            "I'm not connected to your Google Calendar yet. Ask me to connect (or hit "
            "/integrations/google/connect) to grant read-only access."
        )
    except EncryptionUnavailableError:
        return "I can't read your calendar yet — the encryption key isn't configured on the server."
    except Exception as exc:  # noqa: BLE001 — friendly message to the user, detail to the logs.
        log.error("week_reply_failed", error=str(exc), error_type=type(exc).__name__)
        return "Sorry — I couldn't reach your calendar just now. Try again in a moment."


async def _remember_schedule(session, conversation_id: int, text: str, range_key: str) -> None:
    """Record a schedule read as the active task so a bare range follow-up ("this month") refines it."""
    time_range = ranges.range_from_key(range_key)
    await task_state.remember(
        session,
        conversation_id,
        intent="schedule_range",
        source_types=["calendar"],
        time_range=time_range.as_dict() if time_range else {},
        query=text,
    )


async def _resolve_reference(session, conversation_id: int) -> str | None:
    """Best available subject for a bare "is this on my calendar?" — from the active task, else None."""
    active = await task_state.get_active(session, conversation_id)
    if active is None:
        return None
    return active.unresolved_reference or active.active_person_name or active.active_query


async def _handle_followup(session, conversation_id: int, text: str) -> str | None:
    """Refine the active task with a bare follow-up ("LuAnn", "this month"), or None to fall through.

    Reached only after every deterministic intent declined the message, so a short reference here is
    almost always a continuation — not a new request. Re-scoping re-remembers the task so a chain of
    refinements ("LuAnn" → "LuAnn Williams") keeps working.
    """
    active = await task_state.get_active(session, conversation_id)
    if active is None:
        return None

    if active.active_intent == "schedule_range":
        time_range = ranges.parse_range(text)
        if time_range is not None:
            reply = await schedule_range_handler.handle(text, time_range)
            await task_state.remember(
                session, conversation_id, intent="schedule_range",
                source_types=["calendar"], time_range=time_range.as_dict(), query=text,
            )
            return reply

    if active.active_intent == "email_event_search" and task_state.looks_like_bare_reference(text):
        person = text.strip()
        reply = await email_event_handler.handle(text, person=person)
        await task_state.remember(
            session, conversation_id, intent="email_event_search",
            source_types=["gmail"], query=text, person_name=person,
        )
        return reply

    if active.active_intent == "calendar_verification" and task_state.looks_like_bare_reference(text):
        subject = text.strip()
        reply = await verify_handler.handle(subject)
        await task_state.remember(
            session, conversation_id, intent="calendar_verification",
            source_types=["calendar"], query=text, unresolved_reference=subject,
        )
        return reply

    if active.active_intent == "entity_query" and task_state.looks_like_bare_reference(text):
        subject = text.strip()
        reply = await knowledge_handler.handle_entity(subject)
        await task_state.remember(
            session, conversation_id, intent="entity_query",
            query=text, unresolved_reference=subject,
        )
        return reply

    return None


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
