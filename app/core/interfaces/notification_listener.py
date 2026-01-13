from abc import ABC, abstractmethod


class INotificationListener(ABC):
    """Interface for listening to notifications (e.g. from database)."""

    @abstractmethod
    async def start(self, channel: str) -> None:
        """Start listening on the specified channel."""
        ...

    @abstractmethod
    async def wait(self, timeout: float | None = None) -> None:
        """Wait for a notification. Raises TimeoutError if timeout expires."""
        ...

    @abstractmethod
    async def stop(self) -> None:
        """Stop listening and close resources."""
        ...
