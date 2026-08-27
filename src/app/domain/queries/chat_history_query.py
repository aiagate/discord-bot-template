"""Query interface for chat history retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from flow_res import Result

from app.domain.aggregates.chat import Chat
from app.domain.value_objects.chat_type import ChatType

if TYPE_CHECKING:
    from app.domain.repositories.interfaces import RepositoryError


class IChatHistoryQuery(ABC):
    """Query interface for retrieving chat history."""

    @abstractmethod
    async def get_recent_history(
        self,
        chat_type: ChatType,
        limit: int = 20,
    ) -> Result[list[Chat], RepositoryError]:
        """Get recent chat history for a platform."""
        pass
