"""Compose a natural answer by reasoning over grounded evidence (Phase 2D.4).

This is where the LLM finally speaks — but only over the `GroundedContext`, never over a raw provider.
The prompt lets it reason about relationships, priorities, roles, routines, and importance while
forbidding invented facts, and asks for natural prose rather than a labelled database dump. The output
is not trusted blindly: the caller runs it through `guard` before it reaches the user.
"""
from __future__ import annotations

from app import llm
from app.config import get_settings
from app.llm import ChatMessage
from app.reasoning.collect import GroundedContext
from app.telemetry import get_logger

log = get_logger(__name__)

_SYSTEM = """You are Jarvis, {owner}'s personal secretary. You reason over a grounded model of their \
life and answer like a sharp, trusted assistant.

Hard rules — never break these:
- You may reason about relationships, priorities, roles, routines, importance, and likely meaning.
- You may NEVER invent facts. Every concrete detail you state — an event, date, time, place, name, \
email subject or sender, project, or commitment — MUST appear in the EVIDENCE below. If it isn't \
there, you don't know it.
- If the evidence is thin, say what you can and name the uncertainty. If it's absent, say you don't \
have it yet and offer to learn — never fill the gap with a guess.
- Distinguish what Google confirms from what the user told you from what you're inferring, but phrase \
it naturally — don't print the labels.
- If two sources disagree, say so plainly; never hide a conflict.
- You only READ. Never claim you sent, scheduled, moved, or changed anything.

Style: natural, concise, conversational prose. No preamble, no bullet-point data dumps unless a short \
list is genuinely the clearest form. Sound like a person who knows them, not a report generator."""

_USER = """Question: {question}

EVIDENCE (the only facts you may use):
{evidence}
{conflicts}{sources}
Answer the question in natural prose, grounded only in the evidence above."""


def reasoning_available() -> bool:
    """Reasoning needs a real LLM. Under the echo/test provider we defer to the deterministic path."""
    return get_settings().local_llm_provider != "echo"


async def _generate(messages: list[ChatMessage]) -> str:
    settings = get_settings()
    return await llm.generate(messages, temperature=0.3, max_tokens=settings.local_llm_max_tokens)


async def compose(context: GroundedContext) -> str:
    """Turn grounded evidence into a natural answer. Raises on LLM failure (caller handles fallback)."""
    settings = get_settings()
    conflicts = context.conflict_block()
    sources = context.source_block()
    user = _USER.format(
        question=context.question or "(tell me what you know)",
        evidence=context.evidence_block(),
        conflicts=f"\nCONFLICTS to surface honestly:\n{conflicts}\n" if conflicts else "",
        sources=f"\nSOURCE STATUS:\n{sources}\n" if sources else "",
    )
    messages = [
        ChatMessage(
            role="system",
            content=_SYSTEM.format(owner=getattr(settings, "owner_name", None) or "the user"),
        ),
        ChatMessage(role="user", content=user),
    ]
    prose = (await _generate(messages)).strip()
    log.info("reasoning_composed", kind=context.kind, chars=len(prose))
    return prose
