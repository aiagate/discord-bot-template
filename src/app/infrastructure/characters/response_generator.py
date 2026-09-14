"""Generate character responses through a provider-neutral text client."""

from __future__ import annotations

import json

from flow_res import Err, Ok, Result, is_err

from app.contracts.messages.character_prompt import (
    CharacterConversationContext,
    CharacterSelectionContext,
    build_character_response_instruction,
    build_character_selection_instruction,
)
from app.contracts.messages.generated_character_response import (
    CharacterSelection,
    GeneratedCharacterResponse,
)
from app.contracts.messages.llm import TextGenerationRequest, TextGenerationResponse
from app.contracts.ports.character_response_generator import (
    CharacterGenerationError,
    CharacterGenerationErrorType,
    ICharacterResponseGenerator,
)
from app.contracts.ports.llm import ITextGenerationClient, TextGenerationError

MAX_MEMORY_CANDIDATES = 8
MAX_MEMORY_CANDIDATE_LENGTH = 2_000
MAX_SELECTION_SUMMARY_LENGTH = 400

_CHARACTER_SELECTION_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {"character_id": {"type": "string"}},
    "required": ["character_id"],
    "additionalProperties": False,
}
_CHARACTER_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "character_id": {"type": "string"},
        "content": {"type": "string"},
        "memory_candidates": {
            "type": "array",
            "items": {"type": "string"},
        },
        "selection_summary": {"type": "string"},
    },
    "required": [
        "character_id",
        "content",
        "memory_candidates",
        "selection_summary",
    ],
    "additionalProperties": False,
}


class CharacterResponseGenerator(ICharacterResponseGenerator):
    """Map shared character contexts to validated model responses."""

    def __init__(self, client: ITextGenerationClient) -> None:
        """Create a character generator over one provider adapter."""
        self._client = client

    async def aclose(self) -> None:
        """Close the provider adapter owned by this generator."""
        await self._client.aclose()

    async def select_character(
        self, context: CharacterSelectionContext
    ) -> Result[CharacterSelection, CharacterGenerationError]:
        """Select exactly one configured character from the conversation snapshot."""
        result = await self._request_json(
            TextGenerationRequest(
                system_instruction=build_character_selection_instruction(context),
                input_text=context.to_json(),
                output_schema=_CHARACTER_SELECTION_SCHEMA,
                schema_name="character_selection",
            )
        )
        if is_err(result):
            return Err(result.error)
        raw_id = result.value.get("character_id")
        if not isinstance(raw_id, str):
            return Err(_invalid("Model returned an invalid character ID."))
        character_id = raw_id.strip()
        if context.roster.find(character_id) is None:
            return Err(_invalid("Model returned an unknown character ID."))
        return Ok(CharacterSelection(character_id=character_id))

    async def generate(
        self, context: CharacterConversationContext
    ) -> Result[GeneratedCharacterResponse, CharacterGenerationError]:
        """Generate and validate one response for the selected character."""
        result = await self._request_json(
            TextGenerationRequest(
                system_instruction=build_character_response_instruction(context),
                input_text=context.to_json(),
                output_schema=_CHARACTER_RESPONSE_SCHEMA,
                schema_name="character_response",
            )
        )
        if is_err(result):
            return Err(result.error)

        payload = result.value
        raw_id = payload.get("character_id")
        raw_content = payload.get("content")
        if (
            not isinstance(raw_id, str)
            or raw_id.strip() != context.character.character_id
        ):
            return Err(_invalid("Model returned an invalid response character."))
        if not isinstance(raw_content, str) or not raw_content.strip():
            return Err(_invalid("Model returned empty response content."))

        memories = _memory_candidates(payload.get("memory_candidates"))
        if is_err(memories):
            return Err(memories.error)
        summary = _selection_summary(payload.get("selection_summary"))
        if is_err(summary):
            return Err(summary.error)
        return Ok(
            GeneratedCharacterResponse(
                character_id=context.character.character_id,
                content=raw_content.strip(),
                memory_candidates=memories.value,
                selection_summary=summary.value,
            )
        )

    async def _request_json(
        self, request: TextGenerationRequest
    ) -> Result[dict[str, object], CharacterGenerationError]:
        """Generate one JSON payload and classify transport or syntax failures."""
        try:
            response = await self._client.generate(request)
        except TextGenerationError as error:
            return Err(_failed(str(error)))
        except Exception as error:
            return Err(_failed(f"Text generation failed ({type(error).__name__})."))
        return _decode_json(response)


def _decode_json(
    response: TextGenerationResponse,
) -> Result[dict[str, object], CharacterGenerationError]:
    """Decode one provider response without trusting its object shape."""
    try:
        payload = json.loads(response.output_text)
    except (json.JSONDecodeError, UnicodeError):
        return Err(_invalid("Model returned invalid JSON."))
    if not isinstance(payload, dict):
        return Err(_invalid("Model JSON response must be an object."))
    return Ok(payload)


def _memory_candidates(
    raw: object,
) -> Result[tuple[str, ...], CharacterGenerationError]:
    """Validate bounded candidate memories returned by a model."""
    if not isinstance(raw, list) or not all(isinstance(item, str) for item in raw):
        return Err(_invalid("Model returned invalid memory candidates."))
    values = tuple(item.strip() for item in raw if item.strip())
    if len(values) > MAX_MEMORY_CANDIDATES or any(
        len(item) > MAX_MEMORY_CANDIDATE_LENGTH for item in values
    ):
        return Err(_invalid("Model returned too many or too-long memory candidates."))
    return Ok(values)


def _selection_summary(raw: object) -> Result[str | None, CharacterGenerationError]:
    """Validate the optional bounded selection summary."""
    if not isinstance(raw, str):
        return Err(_invalid("Model returned an invalid selection summary."))
    value = raw.strip() or None
    if value is not None and len(value) > MAX_SELECTION_SUMMARY_LENGTH:
        return Err(_invalid("Model returned a too-long selection summary."))
    return Ok(value)


def _invalid(message: str) -> CharacterGenerationError:
    """Build a model-output validation error."""
    return CharacterGenerationError(
        type=CharacterGenerationErrorType.INVALID_RESPONSE,
        message=message,
    )


def _failed(message: str) -> CharacterGenerationError:
    """Build a provider failure without exposing provider credentials."""
    return CharacterGenerationError(
        type=CharacterGenerationErrorType.GENERATION_FAILED,
        message=message,
    )


__all__ = ["CharacterResponseGenerator"]
