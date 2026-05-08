"""Interface for auditable domain entities."""

from datetime import datetime
from typing import Protocol, runtime_checkable


@runtime_checkable
class IAuditable(Protocol):
    """Protocol for entities that support audit timestamps.

    Any domain aggregate implementing this protocol will have
    created_at and updated_at automatically managed by the repository layer.
    """

    created_at: datetime
    updated_at: datetime
