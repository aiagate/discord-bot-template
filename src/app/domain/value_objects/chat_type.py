"""Chat type value object."""

from __future__ import annotations

from enum import StrEnum

from flow_res import Err, Ok, Result


class ChatType(StrEnum):
    """Chat platform types."""

    DISCORD = "DISCORD"
    LINE = "LINE"

    @classmethod
    def from_primitive(cls, value: str) -> Result[ChatType, ValueError]:
        """Create ChatType from string.

        Args:
            value: String representation of chat type

        Returns:
            Ok with ChatType if valid, Err with ValueError otherwise
        """
        try:
            normalized = value.strip()
            if not normalized:
                return Err(ValueError("Chat type cannot be empty."))
            return Ok(cls(normalized.upper()))
        except ValueError:
            return Err(ValueError(f"Invalid chat type: {value}"))

    def to_primitive(self) -> str:
        """Convert to primitive string for persistence."""
        return self.value
