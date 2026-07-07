"""TextChannel abstraction — so SMS/web can replace Telegram later without touching the brain."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class TextChannel(Protocol):
    """A two-way text front door. Implementations own their transport lifecycle."""

    async def start(self) -> None: ...

    async def stop(self) -> None: ...
