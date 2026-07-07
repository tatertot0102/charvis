"""Selects the LLM provider from configuration. Changing providers = changing .env."""
from functools import lru_cache

from app.config import get_settings
from app.llm.anthropic import AnthropicProvider
from app.llm.base import LLMError, LLMProvider
from app.llm.echo import EchoProvider
from app.llm.lmstudio import LMStudioProvider
from app.llm.ollama import OllamaProvider
from app.llm.openai import OpenAIProvider


@lru_cache
def get_provider() -> LLMProvider:
    """Build the configured provider once per process."""
    s = get_settings()
    name = s.local_llm_provider.strip().lower()

    common = {
        "model": s.local_llm_model,
        "base_url": s.local_llm_base_url,
        "temperature": s.local_llm_temperature,
        "max_tokens": s.local_llm_max_tokens,
        "timeout": s.local_llm_timeout,
    }

    if name == "ollama":
        return OllamaProvider(**common)
    if name == "openai":
        return OpenAIProvider(api_key=s.openai_api_key, **common)
    if name == "lmstudio":
        return LMStudioProvider(**common)
    if name == "anthropic":
        return AnthropicProvider(api_key=s.anthropic_api_key, **common)
    if name == "echo":
        return EchoProvider()

    raise LLMError(
        f"Unknown LOCAL_LLM_PROVIDER '{s.local_llm_provider}'. "
        "Expected one of: ollama, openai, anthropic, lmstudio, echo."
    )
