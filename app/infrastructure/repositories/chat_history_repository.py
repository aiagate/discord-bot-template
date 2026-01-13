from sqlalchemy import desc, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.result import Err, Ok, Result
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.repositories.chat_history_repository import IChatHistoryRepository
from app.domain.repositories.interfaces import (
    RepositoryError,
    RepositoryErrorType,
)
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.orm_models.chat_message_orm import ChatMessageORM


class ChatHistoryRepository(IChatHistoryRepository):
    """Implementation of ChatHistoryRepository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def add(self, message: ChatMessage) -> Result[None, RepositoryError]:
        """Add new chat message."""
        try:
            orm_model = ORMMappingRegistry.to_orm(message)
            if not isinstance(orm_model, ChatMessageORM):
                # Should not happen if registry is correct
                return Err(
                    RepositoryError(
                        RepositoryErrorType.UNEXPECTED, "Invalid ORM mapping"
                    )
                )

            self._session.add(orm_model)
            # We need to flush to get the ID if we needed it, but for persistence add is enough till commit.
            # However, domain entity doesn't have ID so it's fine.
            return Ok(None)
        except Exception as e:
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(e)))

    async def get_recent_history(
        self, limit: int = 10
    ) -> Result[list[ChatMessage], RepositoryError]:
        """Get recent chat history."""
        try:
            stmt = (
                select(ChatMessageORM)
                .order_by(desc(ChatMessageORM.sent_at))  # pyright: ignore[reportArgumentType]
                .limit(limit)
            )
            result = await self._session.execute(stmt)
            orm_messages = result.scalars().all()

            # The result comes back in reverse chronological order (newest first).
            # We usually want history in chronological order (oldest first) for context.
            ordered_orms = reversed(orm_messages)

            domain_messages = [ORMMappingRegistry.from_orm(orm) for orm in ordered_orms]

            # Ensure strict type check satisfaction by casting if necessary,
            # though map function usually infers correctly.
            # ORMMappingRegistry.from_orm returns Any, but we know it's ChatMessage.
            return Ok(list(domain_messages))

        except Exception as e:
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(e)))
