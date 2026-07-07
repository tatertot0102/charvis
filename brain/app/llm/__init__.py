"""LLM facade. The ONLY LLM surface the rest of the app uses: `await llm.generate(...)`."""
from collections.abc import Sequence

from app.llm.base import ChatMessage, LLMError, LLMProvider
from app.llm.factory import get_provider


async def generate(
    messages: Sequence[ChatMessage],
    *,
    temperature: float | None = None,
    max_tokens: int | None = None,
) -> str:
    """Generate a reply using the configured provider (selected via .env)."""
    return await get_provider().generate(
        messages, temperature=temperature, max_tokens=max_tokens
    )


__all__ = ["generate", "get_provider", "ChatMessage", "LLMProvider", "LLMError"]
