"""Read-only chat history query application port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime

from flow_res import Result

from app.domain.aggregates.chat_message import ChatMessage
from app.domain.repositories.interfaces import RepositoryError
from app.domain.value_objects import ChatPlatform
from app.domain.value_objects.conversation_scope import ConversationScope


class IChatHistoryQuery(ABC):
    """Query port for retrieving messages within one conversation scope."""

    @abstractmethod
    async def get_recent_history(
        self,
        conversation_scope: ConversationScope,
        limit: int = 20,
        *,
        before: tuple[datetime, str] | None = None,
    ) -> Result[list[ChatMessage], RepositoryError]:
        """Get history before an optional (occurred_at, internal ID) cursor."""
        pass

    @abstractmethod
    async def get_by_external_id(
        self, platform: ChatPlatform, external_message_id: str
    ) -> Result[ChatMessage | None, RepositoryError]:
        """Find an already persisted provider message for idempotent ingestion."""
        pass
