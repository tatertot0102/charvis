"""OpenAI cloud provider (opt-in; requires OPENAI_API_KEY)."""
from app.llm.openai_compat import OpenAICompatProvider


class OpenAIProvider(OpenAICompatProvider):
    DEFAULT_BASE_URL = "https://api.openai.com/v1"
    REQUIRES_API_KEY = True
