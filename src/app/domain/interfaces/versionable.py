"""Interface for entities that support optimistic locking."""

from typing import Protocol, runtime_checkable

from app.domain.value_objects import Version


@runtime_checkable
class IVersionable(Protocol):
    """Protocol for entities that support optimistic locking via version field.

    Any domain aggregate implementing this protocol will have
    version automatically managed by the repository layer.
    """

    version: Version
