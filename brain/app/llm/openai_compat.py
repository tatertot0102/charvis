"""OpenAI-compatible provider base — covers OpenAI and LM Studio (and any /v1 server)."""
from collections.abc import Sequence

import httpx

from app.llm.base import ChatMessage, LLMError, LLMProvider


class OpenAICompatProvider(LLMProvider):
    """POSTs to {base_url}/chat/completions. Subclasses set DEFAULT_BASE_URL / key policy."""

    DEFAULT_BASE_URL = "http://localhost:1234/v1"
    REQUIRES_API_KEY = False

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
        self._base = (base_url or self.DEFAULT_BASE_URL).rstrip("/")
        self._model = model
        self._api_key = api_key
        self._temperature = temperature
        self._max_tokens = max_tokens
        self._timeout = timeout
        if self.REQUIRES_API_KEY and not api_key:
            raise LLMError(f"{type(self).__name__} requires an API key but none was configured")

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
            "temperature": self._temperature if temperature is None else temperature,
            "max_tokens": self._max_tokens if max_tokens is None else max_tokens,
        }
        headers = {"Authorization": f"Bearer {self._api_key}"} if self._api_key else {}
        try:
            async with httpx.AsyncClient(timeout=self._timeout) as client:
                response = await client.post(
                    f"{self._base}/chat/completions", json=payload, headers=headers
                )
                response.raise_for_status()
                data = response.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPError as exc:
            raise LLMError(f"OpenAI-compatible request failed: {exc}") from exc
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"Unexpected completion response shape: {exc}") from exc
