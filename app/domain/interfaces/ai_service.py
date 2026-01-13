from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.result import Result
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.value_objects.ai_provider import AIProvider


@dataclass(frozen=True)
class AIServiceError(Exception):
    """Represents an error from the AI service."""

    message: str

    def __str__(self) -> str:
        return self.message


class IAIService(ABC):
    """Interface for AI service."""

    @abstractmethod
    async def generate_content(
        self,
        prompt: str,
        history: list[ChatMessage],
        system_instruction: str | None = None,
    ) -> Result[str, AIServiceError]:
        """Generate content from prompt.

        Args:
            prompt: The input text prompt.
            prompt: The input text prompt.
            history: The chat history.
            system_instruction: Optional system instruction to override default.

        Returns:
            Result[str, AIServiceError]: generated content or error.
        """
        pass

    @abstractmethod
    async def initialize_ai_agent(self) -> None:
        """Initialize AI agent (e.g. setup caching)."""
        pass

    @property
    @abstractmethod
    def provider(self) -> AIProvider:
        """Get the provider type."""
        pass
