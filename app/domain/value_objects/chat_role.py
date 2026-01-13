"""ChatRole value object."""

from __future__ import annotations

from enum import Enum

from app.core.result import Err, Ok, Result


class ChatRole(str, Enum):
    """Role of the message sender."""

    USER = "user"
    MODEL = "model"

    @classmethod
    def from_primitive(cls, value: str) -> Result[ChatRole, ValueError]:
        """Create ChatRole from string."""
        try:
            return Ok(cls(value.lower()))
        except ValueError:
            return Err(ValueError(f"Invalid chat role: {value}"))
