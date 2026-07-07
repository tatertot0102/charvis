"""Provider-agnostic LLM interface. Application code depends only on these types."""
from abc import ABC, abstractmethod
from collections.abc import Sequence
from dataclasses import dataclass


@dataclass(frozen=True)
class ChatMessage:
    """A single chat turn. role is one of: system | user | assistant."""

    role: str
    content: str


class LLMError(RuntimeError):
    """Raised when a provider fails to produce a completion."""


class LLMProvider(ABC):
    """Interface every backend implements. The rest of the app never imports a concrete provider."""

    @abstractmethod
    async def generate(
        self,
        messages: Sequence[ChatMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> str:
        """Return the assistant's reply text for the given conversation."""
        raise NotImplementedError
