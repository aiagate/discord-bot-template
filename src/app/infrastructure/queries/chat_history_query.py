"""SQLAlchemy implementation of chat history query."""

import logging
from typing import Any, cast

from flow_res import Err, Ok, Result
from sqlalchemy import desc, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.chat import Chat
from app.domain.queries.chat_history_query import IChatHistoryQuery
from app.domain.repositories.interfaces import RepositoryError, RepositoryErrorType
from app.domain.value_objects.chat_type import ChatType
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.orm_models.chat_orm import ChatORM

logger = logging.getLogger(__name__)


class SQLAlchemyChatHistoryQuery(IChatHistoryQuery):
    """SQLAlchemy implementation of chat history query."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_recent_history(
        self,
        chat_type: ChatType,
        limit: int = 20,
    ) -> Result[list[Chat], RepositoryError]:
        """Get recent chat history for the given platform."""
        try:
            table = cast(Any, ChatORM).__table__
            statement = (
                select(ChatORM)
                .where(table.c.type == chat_type.to_primitive())
                .order_by(desc(table.c.created_at), desc(table.c.id))
                .limit(limit)
            )
            result = await self._session.execute(statement)
            orm_items = list(result.scalars().all())
            orm_items.reverse()
            chats = [ORMMappingRegistry.from_orm(item) for item in orm_items]
            return Ok(chats)
        except SQLAlchemyError as e:
            logger.exception("Database error occurred in chat history lookup")
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message=str(e),
                )
            )
