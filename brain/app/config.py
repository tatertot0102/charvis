"""Application configuration — loaded from environment / .env. No hardcoded secrets or hosts."""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


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


@lru_cache
def get_settings() -> Settings:
    """Cached settings accessor so .env is parsed once per process."""
    return Settings()
