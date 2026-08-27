"""ChatId value object."""

from dataclasses import dataclass

from app.domain.value_objects.base_id import BaseId


@dataclass(frozen=True)
class ChatId(BaseId):
    """ChatId value object using ULID.

    Inherits all functionality from BaseId including:
    - generate() for creating new chat IDs
    - to_primitive() / from_primitive() for persistence
    - Immutability and value equality
    """
