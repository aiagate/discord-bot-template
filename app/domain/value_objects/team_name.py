"""TeamName value object with validation."""

from dataclasses import dataclass

from app.core.result import Err, Ok, Result


@dataclass(frozen=True)
class TeamName:
    """TeamName value object with validation.

    This is an immutable value object that wraps a team name string.
    Team names are validated to ensure they meet minimum requirements.

    Implements IValueObject[str] protocol for automatic persistence layer conversion.
    """

    _value: str

    # チーム名の最小・最大文字数
    MIN_LENGTH: int = 1
    MAX_LENGTH: int = 100

    def to_primitive(self) -> str:
        """Convert to primitive string type for persistence.

        Returns:
            String representation suitable for database storage
        """
        return self._value

    @classmethod
    def from_primitive(cls, value: str) -> Result["TeamName", Exception]:
        """Create TeamName from primitive string.

        Args:
            value: String representation of team name from database

        Returns:
            TeamName instance

        Raises:
            ValueError: If the string is not a valid team name
        """
        if not value:
            return Err(ValueError("Team name cannot be empty."))
        if len(value) < cls.MIN_LENGTH:
            return Err(
                ValueError(
                    f"Team name must be at least {cls.MIN_LENGTH} characters long."
                )
            )
        if len(value) > cls.MAX_LENGTH:
            return Err(
                ValueError(f"Team name must not exceed {cls.MAX_LENGTH} characters.")
            )
        # Strip 前後の空白
        normalized = value.strip()
        if not normalized:
            return Err(ValueError("Team name cannot be empty."))
        if len(normalized) < cls.MIN_LENGTH:
            return Err(
                ValueError(
                    f"Team name must be at least {cls.MIN_LENGTH} characters long."
                )
            )
        if len(normalized) > cls.MAX_LENGTH:
            return Err(
                ValueError(f"Team name must not exceed {cls.MAX_LENGTH} characters.")
            )
        return Ok(cls(_value=normalized))

    def __str__(self) -> str:
        """String representation."""
        return self.to_primitive()

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"TeamName({self.to_primitive()})"
