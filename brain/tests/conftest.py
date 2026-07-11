"""Shared test fixtures + hard test-database isolation.

Tests MUST NEVER touch the real ``jarvis`` production database — its ``default`` account holds the
user's real connected Google data (calendar snapshots, commitments, knowledge entities). Because the
chat handlers are single-account (everything runs under account ``default``), a conversation test that
creates a commitment would otherwise write a fixture straight into real production data.

The guard: before ANY app module is imported, we repoint ``DB_DSN`` at a dedicated ``jarvis_test``
database, then bootstrap it from the models. Production data is neither read nor written by the suite.
"""
import asyncio
import os
from urllib.parse import urlparse

import pytest

# --- redirect the whole suite to a dedicated test database BEFORE importing app ---------------
_REAL_DSN = os.environ.get("DB_DSN", "")
if _REAL_DSN:
    _base, _, _name = _REAL_DSN.rpartition("/")
    if not _name.startswith("jarvis_test"):
        os.environ["DB_DSN"] = f"{_base}/jarvis_test"

from app.config import get_settings  # noqa: E402  (must follow the DB_DSN override above)

get_settings.cache_clear()

from app.llm.factory import get_provider  # noqa: E402


async def _bootstrap_test_db() -> None:
    """Create the jarvis_test database if missing, then (re)build a pristine schema from the models."""
    import asyncpg

    import app.db.models  # noqa: F401 — importing registers every table on Base.metadata
    from app.db.base import Base
    from app.db.session import engine

    dsn = os.environ["DB_DSN"].replace("+asyncpg", "")
    parsed = urlparse(dsn)
    dbname = parsed.path.lstrip("/")

    admin = await asyncpg.connect(
        user=parsed.username,
        password=parsed.password,
        host=parsed.hostname,
        port=parsed.port or 5432,
        database="postgres",
    )
    try:
        exists = await admin.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", dbname)
        if not exists:
            await admin.execute(f'CREATE DATABASE "{dbname}"')
    finally:
        await admin.close()

    # Pristine each run: drop then recreate so cross-run data can't leak into global-query providers.
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)


@pytest.fixture(scope="session", autouse=True)
def _isolated_test_db():
    """Fail loudly unless the suite is pointed at jarvis_test, then bootstrap it once per session."""
    dbname = os.environ["DB_DSN"].rpartition("/")[2]
    assert dbname.startswith("jarvis_test"), (
        f"tests must run against jarvis_test, not {dbname!r} — refusing to touch production data"
    )
    asyncio.run(_bootstrap_test_db())
    yield


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """Ensure provider selection is re-read per test (settings/env may be patched)."""
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()
