"""Provider-neutral messages for structured text generation."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class TextGenerationRequest:
    """Describe one text generation request without naming an LLM provider."""

    system_instruction: str
    input_text: str
    output_schema: Mapping[str, object] | None = None
    schema_name: str = "response"
    max_output_tokens: int = 4096

    def __post_init__(self) -> None:
        """Validate and detach the request's mutable schema."""
        if not self.input_text.strip():
            raise ValueError("Text generation input must not be empty.")
        if self.output_schema is not None:
            schema = dict(self.output_schema)
            if not schema:
                raise ValueError("Text generation output schema must not be empty.")
            object.__setattr__(self, "output_schema", schema)
            schema_name = self.schema_name.strip()
            if not schema_name:
                raise ValueError("Text generation schema name must not be empty.")
            object.__setattr__(self, "schema_name", schema_name)
        if self.max_output_tokens <= 0:
            raise ValueError("Text generation output limit must be greater than zero.")


@dataclass(frozen=True, slots=True)
class TextGenerationResponse:
    """Contain the text returned by a provider after one generation request."""

    output_text: str

    def __post_init__(self) -> None:
        """Reject empty provider responses at the shared boundary."""
        if not self.output_text.strip():
            raise ValueError("Text generation response must not be empty.")


__all__ = ["TextGenerationRequest", "TextGenerationResponse"]
