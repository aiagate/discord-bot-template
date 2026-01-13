"""ChatMessageId value object."""

from dataclasses import dataclass

from app.domain.value_objects.base_id import BaseId


@dataclass(frozen=True)
class ChatMessageId(BaseId):
    """ChatMessageId value object using ULID.

    Inherits all functionality from BaseId including:
    - generate() for creating new IDs
    - to_primitive() / from_primitive() for persistence
    - Immutability and value equality
    """
