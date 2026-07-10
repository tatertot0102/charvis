"""Application configuration — loaded from environment / .env. No hardcoded secrets or hosts."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_SYSTEM_PROMPT = (
    "You are Jarvis, a concise and helpful personal secretary. "
    "Answer directly and briefly. If you are unsure what the user wants, ask one short "
    "clarifying question rather than guessing.\n\n"
    "TRUTH RULES (never break these):\n"
    "• You may rewrite, summarize, prioritize, and explain — but you must NEVER invent facts. "
    "Never make up calendar events, times, titles, recurrences, email subjects, senders, or people. "
    "The user's calendar, email, and your stored notes are the only sources of truth.\n"
    "• You do NOT have the user's live schedule in this message. If they ask what's on their "
    "calendar or what their day/week looks like, do not list events from memory or guess — say you'll "
    "pull it up.\n"
    "• You cannot change the calendar in this reply. NEVER claim you have updated, added, scheduled, "
    "moved, deleted, or cancelled anything. If the user wants a change, say you can draft it and that "
    "they must reply CONFIRM to apply it.\n"
    "• Never output placeholder text like “[insert …]” or “[your …]”. If you don't have real "
    "information, say so plainly and ask."
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

    # --- Calendar actions (Phase 2D: writes, always draft-then-confirm) ---
    calendar_action_ttl_minutes: int = 30  # a pending proposal past this cannot be confirmed
    default_event_duration_minutes: int = 60  # duration for a created event with no explicit end
    workday_start_hour: int = 9  # free-time search / new-event day bounds (local tz)
    workday_end_hour: int = 18
    free_time_min_slot_minutes: int = 30  # smallest gap reported as "free"

    # --- Calendar resolution hardening (Phase 2D.1) ---
    calendar_action_lookback_days: int = 7  # how far *back* resolution searches for a target event
    calendar_action_lookahead_days: int = 180  # how far *ahead* resolution searches (bulk "future")
    calendar_action_min_confidence: float = 0.5  # never draft/execute a match below this confidence
    calendar_bulk_preview_count: int = 5  # how many matched events a bulk proposal previews
    calendar_bulk_max: int = 200  # hard cap on events a single bulk action may touch

    # --- Truthful calendar state (Phase 2D.2: snapshots + commitments) ---
    calendar_snapshot_back_days: int = 1  # how far back the snapshot cache mirrors real events
    calendar_snapshot_forward_days: int = 21  # how far ahead the snapshot cache mirrors (≥ a week)
    week_span_days: int = 7  # how many days a "what's my week?" answer covers

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
