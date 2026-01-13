"""AI Provider enum."""

from enum import Enum

from app.core.result import Err, Ok, Result


class AIProvider(str, Enum):
    """Enum for AI Providers."""

    GEMINI = "Gemini"
    GPT = "GPT"
    MOCK = "Mock"

    @classmethod
    def from_primitive(cls, value: str) -> Result["AIProvider", ValueError]:
        """Create AIProvider from string."""
        try:
            return Ok(cls(value))
        except ValueError:
            return Err(ValueError(f"Invalid AI provider: {value}"))
