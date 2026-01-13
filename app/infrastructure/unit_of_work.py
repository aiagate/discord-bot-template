"""SQLAlchemy Unit of Work implementation."""

from typing import Any, overload

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.result import Err, Ok, Result
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.aggregates.command import Command
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.repositories.chat_history_repository import IChatHistoryRepository
from app.domain.repositories.command_repository import ICommandRepository
from app.domain.repositories.interfaces import (
    IRepository,
    IRepositoryWithId,
    IUnitOfWork,
    RepositoryError,
    RepositoryErrorType,
)
from app.domain.repositories.system_instruction_repository import (
    ISystemInstructionRepository,
)
from app.infrastructure.repositories.generic_repository import GenericRepository


class SQLAlchemyUnitOfWork(IUnitOfWork):
    """SQLAlchemy implementation of Unit of Work."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory
        self._session: AsyncSession | None = None
        self._repositories: dict[tuple[type, ...], Any] = {}

    @overload
    def GetRepository(  # pyright: ignore[reportOverlappingOverload]
        self, entity_type: type[ChatMessage]
    ) -> IChatHistoryRepository: ...

    @overload
    def GetRepository(self, entity_type: type[Command]) -> ICommandRepository: ...

    @overload
    def GetRepository(
        self, entity_type: type[SystemInstruction]
    ) -> ISystemInstructionRepository: ...

    @overload
    def GetRepository[T](self, entity_type: type[T]) -> IRepository[T]: ...

    @overload
    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K]
    ) -> IRepositoryWithId[T, K]: ...

    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K] | None = None
    ) -> (
        IRepository[T]
        | IRepositoryWithId[T, K]
        | "IChatHistoryRepository"
        | ICommandRepository
        | "ISystemInstructionRepository"
        # The return type annotation here is tricky with circular deps and conditional imports.
        # We can use Any or a string forward reference if types are available at runtime or strict checking matches.
        | Any
    ):
        """Get repository for entity type.

        Overloaded method:
        - GetRepository(ChatMessage) -> IChatHistoryRepository
        - GetRepository(Command) -> ICommandRepository
        - GetRepository(SystemInstruction) -> ISystemInstructionRepository
        - GetRepository(User) -> IRepository[User] (save only)
        - GetRepository(User, UserId) -> IRepositoryWithId[User, UserId] (all ops)
        """
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork session not initialized. Use 'async with' context."
            )

        # Handle specialized repositories
        if entity_type is ChatMessage:
            from app.infrastructure.repositories.chat_history_repository import (
                ChatHistoryRepository,
            )

            return ChatHistoryRepository(self._session)

        if entity_type is Command:
            from app.infrastructure.repositories.command_repository import (
                SQLAlchemyCommandRepository,
            )

            return SQLAlchemyCommandRepository(self._session)

        if entity_type is SystemInstruction:
            from app.infrastructure.repositories.system_instruction_repository import (
                SqlAlchemySystemInstructionRepository,
            )

            return SqlAlchemySystemInstructionRepository(self._session)

        # Cache key includes key_type if provided
        cache_key = (entity_type, key_type) if key_type else (entity_type,)

        # Return cached repository if exists
        if cache_key in self._repositories:
            return self._repositories[cache_key]

        # Create new repository
        repository = GenericRepository[T, K](self._session, entity_type, key_type)
        self._repositories[cache_key] = repository
        return repository

    async def commit(self) -> Result[None, RepositoryError]:
        """Commit the transaction."""
        if self._session is None:
            raise RuntimeError("UnitOfWork session not initialized.")
        try:
            await self._session.commit()
            return Ok(None)
        except SQLAlchemyError as e:
            return Err(
                RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(e))
            )

    async def rollback(self) -> None:
        """Rollback the transaction."""
        if self._session is None:
            raise RuntimeError("UnitOfWork session not initialized.")
        await self._session.rollback()

    async def __aenter__(self) -> "SQLAlchemyUnitOfWork":
        """Enter async context manager."""
        self._session = self._session_factory()
        await self._session.__aenter__()
        return self

    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager with auto-rollback."""
        if self._session is None:
            return

        try:
            if exc_type is not None:
                # Exception occurred - rollback
                await self.rollback()
        finally:
            await self._session.__aexit__(exc_type, exc_val, exc_tb)
            self._session = None
            self._repositories.clear()
