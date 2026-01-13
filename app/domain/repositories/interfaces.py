"""Repository interfaces for domain layer."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto
from typing import TYPE_CHECKING, Any, overload

from app.core.result import Result
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.aggregates.command import Command
from app.domain.aggregates.system_instruction import SystemInstruction

if TYPE_CHECKING:
    from app.domain.repositories.chat_history_repository import IChatHistoryRepository
    from app.domain.repositories.command_repository import ICommandRepository
    from app.domain.repositories.system_instruction_repository import (
        ISystemInstructionRepository,
    )


class RepositoryErrorType(Enum):
    """Enum for repository error types."""

    NOT_FOUND = auto()
    UNEXPECTED = auto()
    VERSION_CONFLICT = auto()
    ALREADY_EXISTS = auto()


@dataclass(frozen=True)
class RepositoryError(Exception):
    """Represents a specific error from a repository."""

    type: RepositoryErrorType
    message: str


class IRepository[T](ABC):
    """Repository interface for add and delete operations.

    Use this when you need to add or delete entities without ID-based retrieval.
    Does not require knowledge of ID type.

    Type Parameters:
        T: Entity type (e.g., User, Order)
    """

    @abstractmethod
    async def add(self, entity: T) -> Result[T, RepositoryError]:
        """Add new entity.

        Returns ALREADY_EXISTS error if entity already exists in the database.
        """
        pass

    @abstractmethod
    async def update(self, entity: T) -> Result[T, RepositoryError]:
        """Update existing entity.

        Returns NOT_FOUND error if entity doesn't exist in the database.
        """
        pass

    @abstractmethod
    async def delete(self, entity: T) -> Result[None, RepositoryError]:
        """Delete entity."""
        pass


class IRepositoryWithId[T, K](IRepository[T], ABC):
    """Repository interface with ID-based get operation.

    Extends IRepository[T] with get_by_id operation.
    Use this when you need to retrieve entities by ID.

    Type Parameters:
        T: Entity type (e.g., User, Order)
        K: Primary key type (e.g., int, str, UserId)
    """

    @abstractmethod
    async def get_by_id(self, id: K) -> Result[T, RepositoryError]:
        """Get entity by ID."""
        pass


class IUnitOfWork(ABC):
    """Unit of Work interface for transaction management."""

    @overload
    def GetRepository(self, entity_type: type[ChatMessage]) -> "IChatHistoryRepository":  # pyright: ignore[reportOverlappingOverload]
        """Get repository for ChatHistory."""
        ...

    @overload
    def GetRepository(self, entity_type: type[Command]) -> "ICommandRepository":
        """Get repository for Command."""
        ...

    @overload
    def GetRepository(
        self, entity_type: type[SystemInstruction]
    ) -> "ISystemInstructionRepository":
        """Get repository for SystemInstruction."""
        ...

    @overload
    def GetRepository[T](self, entity_type: type[T]) -> IRepository[T]:
        """Get repository for add and delete operations.

        Args:
            entity_type: The domain entity type (e.g., User)

        Returns:
            Repository instance with add and delete operations
        """
        ...

    @overload
    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K]
    ) -> IRepositoryWithId[T, K]:
        """Get repository with ID-based get operation.

        Args:
            entity_type: The domain entity type (e.g., User)
            key_type: The primary key type (e.g., int, str, UserId)

        Returns:
            Repository instance with all operations (add, delete, get_by_id)
        """
        ...

    @abstractmethod
    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K] | None = None
    ) -> (
        IRepository[T]
        | IRepositoryWithId[T, K]
        | "IChatHistoryRepository"
        | "ICommandRepository"
        | "ISystemInstructionRepository"
    ):
        """Get repository for entity type.

        This method is overloaded:
        - GetRepository(ChatMessage) -> IChatHistoryRepository
        - GetRepository(Command) -> ICommandRepository
        - GetRepository(SystemInstruction) -> ISystemInstructionRepository
        - GetRepository(User) -> IRepository[User] (add, delete)
        - GetRepository(User, UserId) -> IRepositoryWithId[User, UserId] (add, delete, get_by_id)

        Args:
            entity_type: The domain entity type
            key_type: Optional primary key type

        Returns:
            Repository instance
        """
        pass

    @abstractmethod
    async def commit(self) -> Result[None, "RepositoryError"]:
        """Commit the transaction."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Rollback the transaction."""
        pass

    @abstractmethod
    async def __aenter__(self) -> "IUnitOfWork":
        """Enter async context manager."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Exit async context manager with auto-commit/rollback."""
        pass
