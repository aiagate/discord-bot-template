"""Email value object with validation."""

import re
from dataclasses import dataclass
from typing import ClassVar

from app.core.result import Err, Ok, Result


@dataclass(frozen=True)
class Email:
    """Email value object with validation.

    This is an immutable value object that wraps an email address string.
    Email addresses are validated using a regex pattern.

    Implements IValueObject[str] protocol for automatic persistence layer conversion.
    """

    _value: str

    # RFC 5322準拠の簡易的な正規表現パターン
    # - ローカル部: 英数字、ドット、アンダースコア、パーセント、プラス、ハイフン
    # - ドメイン部: 英数字とハイフン、最後はドット + 2文字以上のTLD
    EMAIL_REGEX: ClassVar[re.Pattern[str]] = re.compile(
        r"^[a-zA-Z0-9_%+-]+(?:\.[a-zA-Z0-9_%+-]+)*@"
        r"[a-zA-Z0-9-]+(?:\.[a-zA-Z0-9-]+)*\.[a-zA-Z]{2,}$"
    )

    def to_primitive(self) -> str:
        """Convert to primitive string type for persistence.

        Returns:
            String representation suitable for database storage
        """
        return self._value

    @classmethod
    def from_primitive(cls, value: str) -> Result["Email", Exception]:
        """Create Email from primitive string.

        Args:
            value: String representation of email from database

        Returns:
            Email instance

        Raises:
            ValueError: If the string is not a valid email format
        """
        if not value:
            return Err(ValueError("Email cannot be empty."))
        normalized = value.strip()
        if not normalized:
            return Err(ValueError("Email cannot be empty."))
        if not cls.EMAIL_REGEX.match(normalized):
            return Err(ValueError(f"Invalid email format: {normalized}"))
        return Ok(cls(_value=normalized))

    def __str__(self) -> str:
        """String representation."""
        return self.to_primitive()

    def __repr__(self) -> str:
        """Developer-friendly representation."""
        return f"Email({self.to_primitive()})"
