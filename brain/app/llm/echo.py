"""Echo provider — deterministic, no network. Used for tests and offline dev."""
from collections.abc import Sequence

from app.llm.base import ChatMessage, LLMProvider


class EchoProvider(LLMProvider):
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        last_user = next(
            (m.content for m in reversed(list(messages)) if m.role == "user"), ""
        )
        return f"echo: {last_user}"
