"""DisplayName value object with validation."""

from dataclasses import dataclass

from flow_res import Err, Ok, Result


@dataclass(frozen=True)
class DisplayName:
    """DisplayName value object with validation.

    This is an immutable value object that wraps a display name string.
    Display names are validated to ensure they meet minimum requirements.

    Implements IValueObject[str] protocol for automatic persistence layer conversion.
    """

    _value: str

    # ディスプレイネームの最小・最大文字数
    MIN_LENGTH: int = 1
    MAX_LENGTH: int = 100

    def to_primitive(self) -> str:
        """Convert to primitive string type for persistence.

        Returns:
            String representation suitable for database storage
        """
        return self._value

    @classmethod
    def from_primitive(cls, value: str) -> Result["DisplayName", Exception]:
        """Create DisplayName from primitive string.

        Args:
            value: String representation of display name from database

        Returns:
            DisplayName instance

        Raises:
            ValueError: If the string is not a valid display name
        """
        if not value:
            return Err(ValueError("Display name cannot be empty."))
        if len(value) < cls.MIN_LENGTH:
            return Err(
                ValueError(
                    f"Display name must be at least {cls.MIN_LENGTH} characters long."
                )
            )
        if len(value) > cls.MAX_LENGTH:
            return Err(
                ValueError(f"Display name must not exceed {cls.MAX_LENGTH} characters.")
            )
        if value != value.strip():
            return Err(
                ValueError("Display name cannot have leading or trailing whitespace.")
            )
        return Ok(cls(_value=value))

    def __str__(self) -> str:
        """String representation."""
        return self.to_primitive()

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"DisplayName({self.to_primitive()})"
