"""Shared test fixtures."""
import pytest

from app.llm.factory import get_provider


@pytest.fixture(autouse=True)
def _reset_provider_cache():
    """Ensure provider selection is re-read per test (settings/env may be patched)."""
    get_provider.cache_clear()
    yield
    get_provider.cache_clear()
