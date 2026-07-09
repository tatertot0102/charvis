"""Application configuration — loaded from environment / .env. No hardcoded secrets or hosts."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "You are Jarvis, a concise and helpful personal secretary. "
    "Answer directly and briefly. If you are unsure what the user wants, ask one short "
    "clarifying question rather than guessing."
)


class Settings(BaseSettings):
    """All machine-specific values live here, sourced from the environment.

    Fields without defaults are required — the app fails fast at startup if they are missing
    (see EXECUTION_PLAN §12: validate at boundaries, fail loudly).
    """

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = "development"
    bind_port: int = 8000
    tz: str = "UTC"

    # Required — no default on purpose.
    auth_shared_token: str
    db_dsn: str

    # --- LLM (provider-agnostic; the app only ever calls app.llm.generate) ---
    # Provider is selected by name; no application code references a specific vendor.
    local_llm_provider: str = "ollama"  # ollama | openai | anthropic | lmstudio | echo
    local_llm_base_url: str | None = None  # provider-specific default used when unset
    local_llm_model: str = "llama3.2:3b"
    local_llm_temperature: float = 0.7
    local_llm_max_tokens: int = 1024
    local_llm_timeout: float = 120.0  # seconds; a 3B model on 8 GB can be slow

    # Only used when the matching provider is selected.
    openai_api_key: str | None = None
    anthropic_api_key: str | None = None

    # --- Telegram (bot is disabled unless a token is set) ---
    telegram_bot_token: str | None = None
    telegram_allowed_user_ids: str = ""  # comma-separated numeric ids; empty = allow all

    # --- Conversation ---
    system_prompt: str = DEFAULT_SYSTEM_PROMPT
    history_limit: int = 20  # max prior messages sent to the model

    # --- Secrets at rest (Fernet key; required only when an OAuth integration is used) ---
    secret_encryption_key: str | None = None

    # --- Google (Phase 2A: read-only Calendar) ---
    google_client_id: str | None = None
    google_client_secret: str | None = None
    google_oauth_redirect_uri: str = "http://localhost:8000/integrations/google/callback"

    # --- Gmail (Phase 2B: read-only) ---
    gmail_unread_max: int = 20  # max messages returned by unread/today/search endpoints
    gmail_sync_max_threads: int = 25  # recent threads scanned per sync (bounds API calls)
    gmail_sync_window_days: int = 14  # how far back a sync looks
    waiting_followup_days: int = 4  # age after which "waiting on them" recommends a nudge

    # --- Unified intelligence (Phase 2C: cross-source context + meeting prep) ---
    upcoming_window_days: int = 7  # how far ahead "next meeting" / upcoming events looks
    deadline_window_days: int = 14  # how far ahead deadlines are aggregated
    event_email_lookback_days: int = 30  # window for finding emails related to an event
    context_max_related_emails: int = 5  # cap on related emails pulled per event

    # --- Memory / deep context (Phase 2C.5: consolidation over existing data) ---
    memory_email_lookback_days: int = 180  # how far back the Gmail mirror is scanned (~6 months)
    memory_calendar_back_days: int = 90  # long-range calendar lookback for consolidation
    memory_calendar_forward_days: int = 90  # long-range calendar lookahead for consolidation
    memory_capture_limit: int = 500  # max captures scanned per consolidation run
    memory_telegram_message_limit: int = 500  # max chat messages scanned per consolidation run

    @property
    def telegram_allowed_ids(self) -> set[int]:
        return {int(x) for x in self.telegram_allowed_user_ids.split(",") if x.strip()}


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so .env is parsed once per process."""
    return Settings()
