"""SQLAlchemy implementation of conversation-scoped history queries."""

import logging
from datetime import datetime
from typing import Any, cast

from flow_res import Err, Ok, Result
from sqlalchemy import and_, desc, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.ports.chat_history_query import IChatHistoryQuery
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import ChatPlatform
from app.domain.value_objects.conversation_scope import (
    ConversationScope,
    DiscordConversationScope,
)
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.orm_models.chat_message_orm import ChatMessageORM

logger = logging.getLogger(__name__)


class SQLAlchemyChatHistoryQuery(IChatHistoryQuery):
    """Read ChatMessage rows for one exact conversation scope."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create a query that owns one read session per call."""
        self._session_factory = session_factory

    async def get_recent_history(
        self,
        conversation_scope: ConversationScope,
        limit: int = 20,
        *,
        before: tuple[datetime, str] | None = None,
    ) -> Result[list[ChatMessage], RepositoryError]:
        """Get recent messages for a conversation in chronological order."""
        try:
            if limit <= 0:
                return Err(
                    RepositoryError(
                        type=RepositoryErrorType.UNEXPECTED,
                        message="History limit must be greater than zero.",
                    )
                )

            async with self._session_factory() as session:
                table = cast(Any, ChatMessageORM).__table__
                scope_column = table.c.conversation_scope
                scope_conditions: list[Any]
                if isinstance(conversation_scope, DiscordConversationScope):
                    scope_conditions = [
                        scope_column["guild_id"].as_string()
                        == conversation_scope.guild_id,
                        scope_column["channel_id"].as_string()
                        == conversation_scope.channel_id,
                    ]
                else:
                    scope_conditions = [
                        scope_column["kind"].as_string()
                        == conversation_scope.kind.value,
                        scope_column["locator"].as_string()
                        == conversation_scope.locator,
                    ]
                if before is not None:
                    occurred_at, message_id = before
                    if occurred_at.tzinfo is None or occurred_at.utcoffset() is None:
                        raise ValueError("History cursor must be timezone-aware.")
                    scope_conditions.append(
                        or_(
                            table.c.occurred_at < occurred_at,
                            and_(
                                table.c.occurred_at == occurred_at,
                                table.c.id < message_id,
                            ),
                        )
                    )
                statement = (
                    select(ChatMessageORM)
                    .where(
                        table.c.platform == conversation_scope.platform.to_primitive(),
                        *scope_conditions,
                    )
                    .order_by(desc(table.c.occurred_at), desc(table.c.id))
                    .limit(limit)
                )
                result = await session.execute(statement)
                rows = list(reversed(result.scalars().all()))
                messages = [ORMMappingRegistry.from_orm(row) for row in rows]
                if not all(isinstance(message, ChatMessage) for message in messages):
                    raise TypeError("Chat history mapping returned an invalid entity.")
                return Ok(cast(list[ChatMessage], messages))
        except (SQLAlchemyError, TypeError, ValueError) as error:
            logger.exception("Database error occurred in chat history lookup")
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message=str(error),
                )
            )

    async def get_by_external_id(
        self, platform: ChatPlatform, external_message_id: str
    ) -> Result[ChatMessage | None, RepositoryError]:
        """Find one message by its provider identity."""
        try:
            async with self._session_factory() as session:
                table = cast(Any, ChatMessageORM).__table__
                result = await session.execute(
                    select(ChatMessageORM).where(
                        table.c.platform == platform.to_primitive(),
                        table.c.external_message_id == external_message_id,
                    )
                )
                row = result.scalar_one_or_none()
                if row is None:
                    return Ok(None)
                message = ORMMappingRegistry.from_orm(row)
                if not isinstance(message, ChatMessage):
                    raise TypeError("Chat mapping returned an invalid entity.")
                return Ok(message)
        except (SQLAlchemyError, TypeError, ValueError) as error:
            return Err(
                RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(error))
            )
