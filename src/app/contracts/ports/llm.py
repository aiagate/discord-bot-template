"""Application port for replaceable text-generation providers."""

from abc import ABC, abstractmethod
from types import TracebackType
from typing import Self

from app.contracts.messages.llm import TextGenerationRequest, TextGenerationResponse


class TextGenerationError(Exception):
    """Represent a provider, transport, timeout, or empty-response failure."""


class ITextGenerationClient(ABC):
    """Generate text through a provider-independent asynchronous boundary."""

    @abstractmethod
    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        """Generate one response and raise ``TextGenerationError`` on failure."""
        pass

    @abstractmethod
    async def aclose(self) -> None:
        """Release the provider client's network resources."""
        pass

    async def __aenter__(self) -> Self:
        """Return this client for use in an async context manager."""
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        """Close the provider client when its async context ends."""
        del exc_type, exc_value, traceback
        await self.aclose()


__all__ = ["ITextGenerationClient", "TextGenerationError"]
