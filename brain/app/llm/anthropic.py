"""Anthropic provider (opt-in; requires ANTHROPIC_API_KEY). Uses the Messages API."""
from collections.abc import Sequence

import httpx

from app.llm.base import ChatMessage, LLMError, LLMProvider

ANTHROPIC_VERSION = "2023-06-01"


class AnthropicProvider(LLMProvider):
    DEFAULT_BASE_URL = "https://api.anthropic.com"

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        api_key: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 120.0,
    ) -> None:
        if not api_key:
            raise LLMError("AnthropicProvider requires an API key but none was configured")
        self._base = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._model = model
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout

    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        # Anthropic takes the system prompt separately from the user/assistant turns.
        system = "\n".join(m.content for m in messages if m.role == "system") or None
        turns = [
            {"role": m.role, "content": m.content}
            for m in messages
            if m.role in ("user", "assistant")
        ]
        payload: dict = {
            "model": self._model,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
            "temperature": self._temperature if temperature is None else temperature,
            "messages": turns,
        }
        if system:
            payload["system"] = system
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/v1/messages", json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
            return "".join(
                block["text"] for block in data["content"] if block.get("type") == "text"
            )
        except httpx.HTTPError as exc:
            raise LLMError(f"Anthropic request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise LLMError(f"Unexpected Anthropic response shape: {exc}") from exc
