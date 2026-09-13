"""Repository interfaces for domain layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from flow_res import Result


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
    """Repository interface for add and update operations.

    Use this when you need to add or update entities without ID-based retrieval.
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
        """Update an existing versioned entity with optimistic locking.

        Returns NOT_FOUND for missing rows and VERSION_CONFLICT for stale versions.
        """
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
