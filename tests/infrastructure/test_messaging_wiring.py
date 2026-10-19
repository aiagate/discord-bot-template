"""Tests for the event bus wiring (process-local events only)."""

import importlib.metadata as md
import importlib.util

from injector import Injector

from app import container
from app.contracts.ports import IEventBus
from app.infrastructure.messaging.in_memory_event_bus import InMemoryEventBus


def _requirement_name(requirement: str) -> str:
    """Return the distribution name of a PEP 508 requirement string."""
    name = requirement.split(";")[0]
    for separator in ("<", ">", "=", "!", "[", " ", "("):
        name = name.split(separator, 1)[0]
    return name.strip().lower()


def test_container_provides_in_memory_event_bus() -> None:
    """The DI container wires the process-local InMemoryEventBus."""
    injector = Injector([container.configure])

    assert isinstance(injector.get(IEventBus), InMemoryEventBus)


def test_redis_event_bus_module_is_removed() -> None:
    """The unused RedisEventBus implementation no longer exists."""
    spec = importlib.util.find_spec("app.infrastructure.messaging.redis_event_bus")

    assert spec is None


def test_redis_dependency_is_removed() -> None:
    """The redis package is no longer a declared dependency."""
    requirements = md.requires("app") or []
    redis_requirements = [
        requirement
        for requirement in requirements
        if _requirement_name(requirement) == "redis"
    ]

    assert redis_requirements == []
