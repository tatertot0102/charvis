"""LM Studio provider (local OpenAI-compatible server; no API key required)."""
from app.llm.openai_compat import OpenAICompatProvider


class LMStudioProvider(OpenAICompatProvider):
    DEFAULT_BASE_URL = "http://localhost:1234/v1"
    REQUIRES_API_KEY = False
