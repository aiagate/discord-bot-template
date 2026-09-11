"""Message author kind value object."""

from __future__ import annotations

from enum import StrEnum

from flow_res import Err, Ok, Result


class AuthorKind(StrEnum):
    """Kind of actor that authored a message."""

    USER = "user"
    BOT = "bot"
    WEBHOOK = "webhook"
    SYSTEM = "system"

    @classmethod
    def from_primitive(cls, value: str) -> Result[AuthorKind, ValueError]:
        """Create an author kind from persisted text."""
        normalized = value.strip().lower()
        if not normalized:
            return Err(ValueError("Author kind cannot be empty."))

        try:
            return Ok(cls(normalized))
        except ValueError:
            return Err(ValueError(f"Invalid author kind: {value}"))

    def to_primitive(self) -> str:
        """Return the lower-case value used by persistence."""
        return self.value
