"""SQLAlchemy source selection and completion markers for user memory."""

from datetime import UTC, datetime, time
from typing import Any, cast
from zoneinfo import ZoneInfo

from flow_res import Err, Ok, Result
from sqlalchemy import exists, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.user_memory import UserMemorySource
from app.contracts.ports.user_memory import IUserMemorySourceStore
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.infrastructure.orm_models.chat_message_orm import ChatMessageORM
from app.infrastructure.orm_models.memory_consolidated_chat_source_orm import (
    MemoryConsolidatedChatSourceORM,
)

JST = ZoneInfo("Asia/Tokyo")


def _repository_error(error: Exception) -> Err[RepositoryError]:
    """Convert a database exception to the application error contract."""
    return Err(RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(error)))


def _as_utc(value: datetime) -> datetime:
    """Normalize a timestamp and reject naive scheduling boundaries."""
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Reference time must be timezone-aware.")
    return value.astimezone(UTC)


def _memory_cutoff(reference_time: datetime) -> datetime:
    """Return the start of the current JST day as a UTC cutoff."""
    current = _as_utc(reference_time).astimezone(JST)
    return datetime.combine(current.date(), time.min, tzinfo=JST).astimezone(UTC)


def _text_content(content: object) -> str | None:
    """Return text content from the normalized MessageContent payload."""
    if not isinstance(content, dict):
        return None
    content_type = content.get("type")
    if not isinstance(content_type, str) or content_type.upper() != "TEXT":
        return None
    payload = content.get("payload")
    if not isinstance(payload, dict):
        return None
    text = payload.get("text")
    return text.strip() if isinstance(text, str) and text.strip() else None


def _occurred_at(value: datetime) -> datetime:
    """Normalize a driver timestamp to an aware UTC value."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class SQLAlchemyUserMemorySourceStore(IUserMemorySourceStore):
    """Read immutable, mapped user messages and record processed source IDs."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create a source store backed by the supplied session factory."""
        self._session_factory = session_factory

    async def list_pending(
        self, *, reference_time: datetime, limit: int = 500
    ) -> Result[list[UserMemorySource], RepositoryError]:
        """Return mapped user and owner-attributed bot messages before today."""
        try:
            if limit <= 0:
                raise ValueError("Memory source limit must be greater than zero.")
            cutoff = _memory_cutoff(reference_time)
            chat_table = cast(Any, ChatMessageORM).__table__
            marker_table = cast(Any, MemoryConsolidatedChatSourceORM).__table__
            statement = (
                select(ChatMessageORM)
                .where(
                    chat_table.c.user_id.is_not(None),
                    func.lower(chat_table.c.author_kind).in_(("user", "bot")),
                    chat_table.c.occurred_at < cutoff,
                    ~exists().where(marker_table.c.chat_message_id == chat_table.c.id),
                )
                .order_by(chat_table.c.occurred_at, chat_table.c.id)
                .limit(limit)
            )
            async with self._session_factory() as session:
                rows = (await session.scalars(statement)).all()
            sources: list[UserMemorySource] = []
            for row in rows:
                if row.user_id is None:
                    continue
                content = _text_content(row.content)
                if content is None:
                    continue
                sources.append(
                    UserMemorySource(
                        message_id=row.id,
                        user_id=row.user_id,
                        platform=row.platform.upper(),
                        author_kind=row.author_kind.lower(),
                        external_sender_id=row.external_sender_id,
                        content=content,
                        occurred_at=_occurred_at(row.occurred_at),
                    )
                )
            return Ok(sources)
        except (SQLAlchemyError, TypeError, ValueError) as error:
            return _repository_error(error)

    async def mark_processed(
        self, message_ids: tuple[str, ...], *, processed_at: datetime
    ) -> Result[None, RepositoryError]:
        """Insert idempotent completion markers for evaluated source rows."""
        try:
            timestamp = _as_utc(processed_at)
            async with self._session_factory() as session, session.begin():
                for message_id in dict.fromkeys(message_ids):
                    if not message_id.strip():
                        raise ValueError("Memory source ID cannot be empty.")
                    existing = await session.get(
                        MemoryConsolidatedChatSourceORM, message_id
                    )
                    if existing is None:
                        session.add(
                            MemoryConsolidatedChatSourceORM(
                                chat_message_id=message_id,
                                consolidated_at=timestamp,
                            )
                        )
            return Ok(None)
        except (SQLAlchemyError, TypeError, ValueError) as error:
            return _repository_error(error)
