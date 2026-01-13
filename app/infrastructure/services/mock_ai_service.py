import logging

from app.core.result import Ok, Result
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.interfaces.ai_service import AIServiceError, IAIService
from app.domain.value_objects.ai_provider import AIProvider

logger = logging.getLogger(__name__)


class MockAIService(IAIService):
    """Mock implementation of AI service."""

    async def generate_content(
        self,
        prompt: str,
        history: list[ChatMessage],
        system_instruction: str | None = None,
    ) -> Result[str, AIServiceError]:
        """Generate mock content."""
        logger.debug(f"MockAIService context: prompt={prompt}, history={history}")
        return Ok("This is a mock response from MockAIService.")

    async def initialize_ai_agent(self) -> None:
        """Initialize AI agent (no-op)."""
        pass

    @property
    def provider(self) -> AIProvider:
        """Get the provider type."""
        return AIProvider.MOCK
