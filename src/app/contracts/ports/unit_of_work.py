"""Unit of Work application port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, overload

from flow_res import Result

from app.domain.repositories.interfaces import (
    IRepository,
    IRepositoryWithId,
    RepositoryError,
)


class IUnitOfWork(ABC):
    """Application boundary for transaction and repository lifecycles."""

    @overload
    def GetRepository[T](self, entity_type: type[T]) -> IRepository[T]:
        """Get a repository without ID-based retrieval."""
        ...

    @overload
    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K]
    ) -> IRepositoryWithId[T, K]:
        """Get a repository with ID-based retrieval."""
        ...

    @abstractmethod
    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K] | None = None
    ) -> IRepository[T] | IRepositoryWithId[T, K]:
        """Get a repository for one domain entity type."""
        pass

    @abstractmethod
    def GetCustomRepository[R](self, port_type: type[R]) -> R:
        """Get a registered repository port within the current transaction."""
        pass

    @abstractmethod
    async def commit(self) -> Result[None, RepositoryError]:
        """Commit the current transaction."""
        pass

    @abstractmethod
    async def rollback(self) -> None:
        """Roll back the current transaction."""
        pass

    @abstractmethod
    async def __aenter__(self) -> IUnitOfWork:
        """Open the transaction scope."""
        pass

    @abstractmethod
    async def __aexit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        """Close the transaction scope."""
        pass
