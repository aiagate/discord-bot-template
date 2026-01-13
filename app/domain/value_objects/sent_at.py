"""SentAt value object."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from app.core.result import Err, Ok, Result


@dataclass(frozen=True)
class SentAt:
    """SentAt value object.

    Represents the time a chat message was sent.
    Implements IValueObject[datetime] protocol.
    """

    _value: datetime

    def to_primitive(self) -> datetime:
        """Convert to primitive datetime."""
        return self._value

    @classmethod
    def from_primitive(cls, value: datetime) -> Result[SentAt, Exception]:
        """Create SentAt from primitive datetime."""
        if not isinstance(value, datetime):  # type: ignore[reportUnnecessaryIsInstance]
            return Err(
                TypeError(f"SentAt must be datetime, got {type(value).__name__}")
            )

        # Ensure it is timezone-aware
        if value.tzinfo is None:
            value = value.replace(tzinfo=UTC)

        return Ok(cls(_value=value))

    @property
    def display_time(self) -> str:
        """Get relative time string (e.g., '5 minutes ago')."""
        now = datetime.now(UTC)
        diff = now - self._value

        seconds = diff.total_seconds()

        if seconds < 60:
            return "just now"
        elif seconds < 3600:
            minutes = int(seconds // 60)
            unit = "minute" if minutes == 1 else "minutes"
            return f"{minutes} {unit} ago"
        elif seconds < 86400:
            hours = int(seconds // 3600)
            unit = "hour" if hours == 1 else "hours"
            return f"{hours} {unit} ago"
        elif seconds < 604800:
            days = int(seconds // 86400)
            unit = "day" if days == 1 else "days"
            return f"{days} {unit} ago"
        else:
            weeks = int(seconds // 604800)
            unit = "week" if weeks == 1 else "weeks"
            return f"{weeks} {unit} ago"

    def __str__(self) -> str:
        return str(self._value)
