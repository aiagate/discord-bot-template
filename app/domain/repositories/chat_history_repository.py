"""Repository interface for chat history."""

from abc import ABC, abstractmethod

from app.core.result import Result
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.repositories.interfaces import RepositoryError


class IChatHistoryRepository(ABC):
    """Repository interface for chat history."""

    @abstractmethod
    async def add(self, message: ChatMessage) -> Result[None, RepositoryError]:
        """Add new chat message."""
        pass

    @abstractmethod
    async def get_recent_history(
        self, limit: int = 10
    ) -> Result[list[ChatMessage], RepositoryError]:
        """Get recent chat history."""
        pass
