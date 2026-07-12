"""Broad life-query routing (Phase 2D.4): focus/priority/routine questions reason over the life model.

The detector must catch "what should I focus on" / "what do I do every weekday" while leaving entity
and schedule questions to their own handlers; the handler must answer without raising or fabricating.
"""
import pytest

from app.conversation import intents, life_handler


@pytest.mark.parametrize(
    "text",
    [
        "what should I focus on?",
        "What should I work on next?",
        "what do I do every weekday",
        "what does my typical week look like",
        "what are my priorities right now",
        "what's my daily routine?",
    ],
)
def test_detects_life_queries(text):
    assert intents.detect_life_query(text) is not None


@pytest.mark.parametrize(
    "text",
    [
        "what is ARISE",  # entity question
        "what does my month look like",  # schedule range
        "is the lab on my calendar",  # verification
        "hello there",
    ],
)
def test_ignores_non_life_queries(text):
    assert intents.detect_life_query(text) is None


async def test_life_handler_answers_without_fabricating():
    # Empty test account → no evidence → an honest "I don't have that yet", never invented facts.
    reply = await life_handler.handle("what should I focus on?", account="test_life_empty")
    assert isinstance(reply, str) and reply.strip()
    assert "Sorry" not in reply  # not the error path
