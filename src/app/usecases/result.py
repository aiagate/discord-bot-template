"""Error types specific to the use case layer."""

from dataclasses import dataclass
from enum import Enum, auto


class ErrorType(Enum):
    """Enum for use case error types."""

    NOT_FOUND = auto()
    VALIDATION_ERROR = auto()
    UNEXPECTED = auto()
    CONCURRENCY_CONFLICT = auto()


@dataclass(frozen=True)
class UseCaseError(Exception):
    """Represents a specific error from a use case."""

    type: ErrorType
    message: str

    def __str__(self) -> str:
        """Return message for exception representation."""
        return self.message
