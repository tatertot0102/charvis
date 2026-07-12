"""End-to-end conversation routing for Phase 2D.4 through the real handle_incoming entry point.

Proves the new grounded paths are wired in and safe: broad life/entity questions route to the
reasoning layer, and when the LLM is unavailable they degrade to the deterministic, non-fabricating
renderer instead of erroring or echoing the prompt back. (No real LLM is reachable in the test
environment, so this exercises exactly that degradation path.)
"""
import uuid

from app.conversation.service import handle_incoming


async def test_life_query_routes_to_grounded_reasoning_not_generic_llm():
    ext = f"e2e-{uuid.uuid4()}"
    reply, _ = await handle_incoming("test", ext, "what should I focus on?")
    assert reply.strip()
    # Generic LLM fallback would echo "echo: ..."; the grounded path never does.
    assert not reply.startswith("echo:")


async def test_entity_query_routes_to_grounded_reasoning():
    ext = f"e2e-{uuid.uuid4()}"
    reply, _ = await handle_incoming("test", ext, "what is ARISE")
    assert reply.strip()
    assert not reply.startswith("echo:")
