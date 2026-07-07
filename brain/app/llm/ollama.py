"""Ollama provider — talks to a local Ollama server's native /api/chat endpoint."""
from collections.abc import Sequence

import httpx

from app.llm.base import ChatMessage, LLMError, LLMProvider


class OllamaProvider(LLMProvider):
    DEFAULT_BASE_URL = "http://localhost:11434"

    def __init__(
        self,
        *,
        model: str,
        base_url: str | None = None,
        temperature: float = 0.7,
        max_tokens: int = 1024,
        timeout: float = 120.0,
    ) -> None:
        self._base = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._model = model
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
        payload = {
            "model": self._model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "stream": False,
            "options": {
                "temperature": self._temperature if temperature is None else temperature,
                "num_predict": self._max_tokens if max_tokens is None else max_tokens,
            },
        }
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(f"{self._base}/api/chat", json=payload)
                response.raise_for_status()
                data = response.json()
            return data["message"]["content"]
        except httpx.HTTPError as exc:
            raise LLMError(f"Ollama request failed: {exc}") from exc
        except (KeyError, ValueError) as exc:
            raise LLMError(f"Unexpected Ollama response shape: {exc}") from exc
