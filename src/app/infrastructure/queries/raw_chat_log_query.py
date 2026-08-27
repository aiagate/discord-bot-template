"""SQLAlchemy implementation of raw chat log query."""

import logging
from datetime import datetime
from typing import Any, cast

from flow_res import Err, Ok, Result
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.queries.raw_chat_log_query import IRawChatLogQuery, RawChatLog
from app.domain.repositories.interfaces import RepositoryError, RepositoryErrorType
from app.domain.value_objects.chat_type import ChatType
from app.infrastructure.orm_models.chat_orm import ChatORM

logger = logging.getLogger(__name__)


class SQLAlchemyRawChatLogQuery(IRawChatLogQuery):
    """SQLAlchemy implementation of raw chat log query."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_raw_chat_log_user_ids(
        self,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> Result[list[str], RepositoryError]:
        """Get distinct user IDs that have raw chat logs."""
        try:
            table = cast(Any, ChatORM).__table__
            statement = (
                select(table.c.user_id).distinct().where(table.c.user_id.is_not(None))
            )
            if since is not None:
                statement = statement.where(table.c.created_at >= since)
            if until is not None:
                statement = statement.where(table.c.created_at <= until)

            statement = statement.order_by(table.c.user_id).limit(limit)
            result = await self._session.execute(statement)
            user_ids = [str(user_id) for user_id in result.scalars().all() if user_id]
            return Ok(user_ids)
        except SQLAlchemyError as e:
            logger.exception("Database error occurred in raw chat log lookup")
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message=str(e),
                )
            )

    async def get_raw_chat_logs(
        self,
        user_id: str,
        chat_type: ChatType,
        since: datetime | None = None,
        until: datetime | None = None,
        limit: int = 1000,
    ) -> Result[list[RawChatLog], RepositoryError]:
        """Get raw chat logs for the given user scope and time window."""
        try:
            table = cast(Any, ChatORM).__table__
            conditions: list[Any] = [
                table.c.user_id == user_id,
                table.c.type == chat_type.to_primitive(),
            ]
            if since is not None:
                conditions.append(table.c.created_at >= since)
            if until is not None:
                conditions.append(table.c.created_at <= until)

            statement = (
                select(ChatORM)
                .where(*conditions)
                .order_by(table.c.created_at, table.c.id)
                .limit(limit)
            )
            result = await self._session.execute(statement)
            orm_items = list(result.scalars().all())
            raw_logs = [
                RawChatLog(
                    id=item.id or "",
                    user_id=item.user_id or "",
                    role=item.role or "",
                    chat_type=chat_type,
                    message_content=item.message_content,
                    created_at=item.created_at,
                )
                for item in orm_items
            ]
            return Ok(raw_logs)
        except SQLAlchemyError as e:
            logger.exception("Database error occurred in raw chat log lookup")
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message=str(e),
                )
            )
