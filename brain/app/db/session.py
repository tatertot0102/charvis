"""Async database engine and session factory."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.config import get_settings

_settings = get_settings()

# NullPool: open a fresh connection per use instead of pooling. asyncpg connections are bound to
# the event loop that created them, so pooling breaks across loops (e.g. per-test loops). At
# single-user scale the connect overhead is negligible, and this keeps the always-on service
# robust to loop lifecycle. pool_pre_ping still guards against stale sockets.
engine = create_async_engine(
    _settings.db_dsn, poolclass=NullPool, pool_pre_ping=True, future=True
)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session in a context manager."""
    async with SessionLocal() as session:
        yield session
