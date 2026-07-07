"""Declarative base for all ORM models. No models yet (Phase 0)."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Shared metadata target for models and Alembic migrations."""
