"""Registry for event handlers to allow decorator-based registration."""

from collections.abc import Awaitable, Callable
from typing import Any

EventHandler = Callable[[dict[str, Any]], Awaitable[None]]
ScheduledTask = Callable[[], Awaitable[None]]


class EventRegistry:
    """Registry to collect handlers decorated with @event_handler or @scheduled_task."""

    def __init__(self) -> None:
        self._handlers: list[tuple[str, EventHandler]] = []
        self._scheduled_tasks: list[tuple[int, ScheduledTask]] = []

    def handle(self, topic: str):
        """Decorator to register a function as an event handler."""

        def decorator(func: EventHandler) -> EventHandler:
            self._handlers.append((topic, func))
            return func

        return decorator

    def scheduled(self, interval_seconds: int):
        """Decorator to register a function as a periodic scheduled task."""

        def decorator(func: ScheduledTask) -> ScheduledTask:
            self._scheduled_tasks.append((interval_seconds, func))
            return func

        return decorator

    @property
    def registered_handlers(self) -> list[tuple[str, EventHandler]]:
        """Return all collected topic-handler pairs."""
        return self._handlers

    @property
    def scheduled_tasks(self) -> list[tuple[int, ScheduledTask]]:
        """Return all collected scheduled tasks with their intervals."""
        return self._scheduled_tasks


# グローバルなレジストリインスタンス
registry = EventRegistry()
event_handler = registry.handle
scheduled_task = registry.scheduled
