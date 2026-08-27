"""Query interface for raw chat log retrieval."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

from flow_res import Result

from app.domain.value_objects.chat_type import ChatType

if TYPE_CHECKING:
    from app.domain.repositories.interfaces import RepositoryError


@dataclass(frozen=True, slots=True)
class RawChatLog:
    """Raw chat log row from SQL storage."""

    id: str
    user_id: str
    role: str
    chat_type: ChatType
    message_content: dict[str, Any]
    created_at: datetime | None


class IRawChatLogQuery(ABC):
    """Query interface for retrieving raw chat logs."""

    @abstractmethod
    async def list_raw_chat_log_user_ids(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> Result[list[str], RepositoryError]:
        """Get distinct user IDs that have raw chat logs in a time window."""
        pass

    @abstractmethod
    async def get_raw_chat_logs(
        self,
        user_id: str,
        chat_type: ChatType,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> Result[list[RawChatLog], RepositoryError]:
        """Get raw chat logs for a user scope and optional time window."""
        pass
