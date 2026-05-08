"""UserId value object."""

from dataclasses import dataclass

from app.domain.value_objects.base_id import BaseId


@dataclass(frozen=True)
class UserId(BaseId):
    """UserId value object using ULID.

    Inherits all functionality from BaseId including:
    - generate() for creating new user IDs
    - to_primitive() / from_primitive() for persistence
    - Immutability and value equality
    """
