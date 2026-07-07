"""Async database engine and session factory."""
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_settings = get_settings()

# pool_pre_ping guards against stale connections on a long-running always-on service.
engine = create_async_engine(_settings.db_dsn, pool_pre_ping=True, future=True)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


@asynccontextmanager
async def get_session() -> AsyncIterator[AsyncSession]:
    """Yield an async session in a context manager."""
    async with SessionLocal() as session:
        yield session
