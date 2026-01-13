from abc import ABC, abstractmethod
from uuid import UUID

from app.domain.aggregates.command import Command


class ICommandRepository(ABC):
    """Interface for command repository."""

    @abstractmethod
    async def dequeue(self) -> Command | None:
        """Dequeue the next pending command."""
        ...

    @abstractmethod
    async def complete(self, command_id: UUID) -> None:
        """Mark command as processed."""
        ...

    @abstractmethod
    async def fail(self, command_id: UUID) -> None:
        """Mark command as failed."""
        ...
