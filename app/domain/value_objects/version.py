"""Version value object for optimistic locking."""

from __future__ import annotations

from dataclasses import dataclass

from flow_res import Err, Ok, Result


@dataclass(frozen=True)
class Version:
    """Version value object for optimistic locking.

    Wraps an integer version number used to detect concurrent modifications.
    Implements IValueObject[int] protocol for automatic persistence conversion.
    """

    _value: int

    def to_primitive(self) -> int:
        """Convert to primitive int for persistence."""
        return self._value

    @classmethod
    def from_primitive(cls, value: int) -> Result[Version, Exception]:
        """Create Version from primitive int with validation.

        Args:
            value: The version number (must be non-negative integer)

        Returns:
            Result containing Version or Exception
        """
        if not isinstance(value, int):  # type: ignore[reportUnnecessaryIsInstance]
            return Err(TypeError(f"Version must be int, got {type(value).__name__}"))
        if value < 0:
            return Err(ValueError("Version must be non-negative"))
        return Ok(cls(_value=value))

    def increment(self) -> Version:
        """Return new Version instance with incremented value.

        Returns:
            New Version with value incremented by 1
        """
        return Version(_value=self._value + 1)

    def __str__(self) -> str:
        return str(self._value)

    def __repr__(self) -> str:
        return f"Version({self._value})"
