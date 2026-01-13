import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol


# Event data structure
@dataclass(frozen=True)
class Event:
    topic: str
    payload: dict[str, Any]
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: datetime = field(default_factory=datetime.now)


# Event handler type definition (async function)
EventHandler = Callable[[Event], Awaitable[None]]


# Event Bus abstract interface (Port)
class IEventBus(Protocol):
    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        """Publish an event."""
        ...

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        """Subscribe to an event topic."""
        ...

    async def start(self) -> None:
        """Start the bus (e.g. start listening for notifications)."""
        ...
