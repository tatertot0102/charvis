"""The factory maps LOCAL_LLM_PROVIDER to the right provider and rejects unknown ones."""
import pytest

from app.config import get_settings
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMError
from app.llm.echo import EchoProvider
from app.llm.factory import get_provider
from app.llm.lmstudio import LMStudioProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai import OpenAIProvider


def _use(monkeypatch, **overrides):
    settings = get_settings()
    for key, value in overrides.items():
        monkeypatch.setattr(settings, key, value, raising=False)
    get_provider.cache_clear()


def test_selects_ollama_by_default(monkeypatch):
    _use(monkeypatch, local_llm_provider="ollama")
    assert isinstance(get_provider(), OllamaProvider)


def test_selects_lmstudio(monkeypatch):
    _use(monkeypatch, local_llm_provider="lmstudio")
    assert isinstance(get_provider(), LMStudioProvider)


def test_selects_openai_with_key(monkeypatch):
    _use(monkeypatch, local_llm_provider="openai", openai_api_key="sk-test")
    assert isinstance(get_provider(), OpenAIProvider)


def test_selects_anthropic_with_key(monkeypatch):
    _use(monkeypatch, local_llm_provider="anthropic", anthropic_api_key="sk-ant-test")
    assert isinstance(get_provider(), AnthropicProvider)


def test_selects_echo(monkeypatch):
    _use(monkeypatch, local_llm_provider="echo")
    assert isinstance(get_provider(), EchoProvider)


def test_openai_without_key_raises(monkeypatch):
    _use(monkeypatch, local_llm_provider="openai", openai_api_key=None)
    with pytest.raises(LLMError):
        get_provider()


def test_unknown_provider_raises(monkeypatch):
    _use(monkeypatch, local_llm_provider="not-a-provider")
    with pytest.raises(LLMError):
        get_provider()
