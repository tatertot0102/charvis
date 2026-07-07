"""OllamaProvider builds the right request and parses the native /api/chat response."""
import httpx
import pytest

from app.llm.base import ChatMessage, LLMError
from app.llm.ollama import OllamaProvider


async def test_ollama_parses_response():
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"message": {"role": "assistant", "content": "hi there"}})

    transport = httpx.MockTransport(handler)
    provider = OllamaProvider(model="llama3.2:3b", base_url="http://ollama:11434")

    # Patch the client factory to use the mock transport.
    import app.llm.ollama as mod

    orig = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    mod.httpx.AsyncClient = fake_client  # type: ignore[attr-defined]
    try:
        reply = await provider.generate([ChatMessage(role="user", content="hello")])
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[attr-defined]

    assert reply == "hi there"
    assert captured["url"].endswith("/api/chat")


async def test_ollama_raises_on_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    transport = httpx.MockTransport(handler)
    provider = OllamaProvider(model="llama3.2:3b", base_url="http://ollama:11434")

    import app.llm.ollama as mod

    orig = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = transport
        return orig(*args, **kwargs)

    mod.httpx.AsyncClient = fake_client  # type: ignore[attr-defined]
    try:
        with pytest.raises(LLMError):
            await provider.generate([ChatMessage(role="user", content="hello")])
    finally:
        mod.httpx.AsyncClient = orig  # type: ignore[attr-defined]
