from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")


def event_listener(topic: str) -> Callable[[T], T]:
    """Decorator to mark a method as an event listener for a specific topic."""

    def decorator(func: T) -> T:
        func._event_bus_topic = topic  # type: ignore
        return func

    return decorator
