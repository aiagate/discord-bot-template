"""Gemini SDK adapter for character selection and response generation."""

import asyncio
import json
import logging
from collections.abc import Mapping
from typing import Any

from flow_res import Err, Ok, Result, is_err
from google import genai
from google.genai import types

from app.contracts.messages import (
    CharacterSelection,
    GeneratedCharacterResponse,
    TimesPost,
)
from app.contracts.messages.character_mcp import CharacterMcpServer
from app.contracts.ports.character_response_generator import (
    CharacterGenerationError,
    CharacterGenerationErrorType,
    ICharacterResponseGenerator,
)
from app.domain.character_memory import (
    MAX_CHARACTER_MEMORY_LENGTH,
    MAX_CHARACTER_MEMORY_SUMMARY_LENGTH,
)

logger = logging.getLogger(__name__)
GENERATION_TIMEOUT_SECONDS = 60.0
MAX_MEMORY_CANDIDATES = 8
MAX_TIMES_POSTS = 12
MAX_TIMES_POST_LENGTH = 4000


def _memory_properties() -> dict[str, types.Schema]:
    return {
        "memory_candidates": types.Schema(
            type=types.Type.ARRAY,
            items=types.Schema(
                type=types.Type.STRING, max_length=MAX_CHARACTER_MEMORY_LENGTH
            ),
            max_items=MAX_MEMORY_CANDIDATES,
        ),
        "selection_summary": types.Schema(
            type=types.Type.STRING, max_length=MAX_CHARACTER_MEMORY_SUMMARY_LENGTH
        ),
    }


def _memory_values(payload: dict[str, Any]) -> tuple[tuple[str, ...], str | None]:
    raw_candidates = payload.get("memory_candidates")
    if raw_candidates is None:
        raw_candidates = []
    if not isinstance(raw_candidates, list) or not all(
        isinstance(candidate, str) for candidate in raw_candidates
    ):
        raise ValueError("Gemini response has invalid memory candidates.")
    candidates = tuple(
        candidate.strip() for candidate in raw_candidates if candidate.strip()
    )
    if len(candidates) > MAX_MEMORY_CANDIDATES or any(
        len(candidate) > MAX_CHARACTER_MEMORY_LENGTH for candidate in candidates
    ):
        raise ValueError("Gemini response has too many or too-long memory candidates.")
    raw_summary = payload.get("selection_summary")
    if raw_summary is not None and not isinstance(raw_summary, str):
        raise ValueError("Gemini response has an invalid selection summary.")
    summary = raw_summary.strip() or None if raw_summary is not None else None
    if summary is not None and len(summary) > MAX_CHARACTER_MEMORY_SUMMARY_LENGTH:
        raise ValueError("Gemini response has a too-long selection summary.")
    return candidates, summary


class GeminiCharacterResponseGenerator(ICharacterResponseGenerator):
    """Generate structured character selections and responses with Gemini."""

    def __init__(
        self,
        client: genai.Client,
        model: str,
        *,
        max_output_tokens: int = 4096,
        mcp_servers: Mapping[str, tuple[CharacterMcpServer, ...]] | None = None,
    ) -> None:
        """Initialize the Gemini character response generator.

        Args:
            client: The Google GenAI client instance.
            model: The Gemini model identifier to use (e.g., 'gemini-2.5-flash').
            max_output_tokens: Maximum number of output tokens to generate.
            mcp_servers: Permitted MCP servers by character name, for replies only.
        """
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens
        self._mcp_servers = dict(mcp_servers or {})

    async def aclose(self) -> None:
        """Close the synchronous and asynchronous GenAI clients."""
        try:
            await self._client.aio.aclose()
        finally:
            self._client.close()

    async def _request_json(
        self,
        *,
        system_instruction: str,
        user_content: str,
        response_schema: types.Schema,
        mcp_servers: tuple[CharacterMcpServer, ...] = (),
    ) -> Result[dict[str, Any], CharacterGenerationError]:
        """Call Gemini and parse one structured JSON object."""
        try:
            config = types.GenerateContentConfig(
                system_instruction=system_instruction,
                max_output_tokens=self._max_output_tokens,
                response_mime_type="application/json",
                response_schema=response_schema,
            )
            async with asyncio.timeout(GENERATION_TIMEOUT_SECONDS):
                if mcp_servers:
                    from app.infrastructure.gemini.mcp_tools import generate_with_mcp

                    response = await generate_with_mcp(
                        self._client,
                        model=self._model,
                        user_content=user_content,
                        config=config,
                        servers=mcp_servers,
                    )
                else:
                    response = await self._client.aio.models.generate_content(
                        model=self._model,
                        contents=user_content,
                        config=config,
                    )
            if response.candidates and response.candidates[0].finish_reason not in {
                None,
                types.FinishReason.STOP,
            }:
                return Err(
                    CharacterGenerationError(
                        type=CharacterGenerationErrorType.INVALID_RESPONSE,
                        message=(
                            "Gemini did not finish the response: "
                            f"{response.candidates[0].finish_reason}"
                        ),
                    )
                )
            usage = response.usage_metadata
            if usage is not None:
                logger.info(
                    "Character generation tokens: input=%s output=%s thoughts=%s",
                    usage.prompt_token_count,
                    usage.candidates_token_count,
                    usage.thoughts_token_count,
                )
            text = response.text
        except asyncio.CancelledError:
            raise
        except Exception as err:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.GENERATION_FAILED,
                    message=(
                        f"MCP-enabled response generation failed ({type(err).__name__})."
                        if mcp_servers
                        else f"Gemini response generation failed: {err}"
                    ),
                )
            )

        if text is None or not text.strip():
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.EMPTY_RESPONSE,
                    message="Gemini returned an empty response.",
                )
            )

        try:
            data = json.loads(text)
        except (json.JSONDecodeError, UnicodeError) as err:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message=f"Failed to parse Gemini response as JSON: {err}",
                )
            )
        if not isinstance(data, dict):
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini response JSON must be an object.",
                )
            )
        return Ok(data)

    async def select_character(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_names: tuple[str, ...],
    ) -> Result[CharacterSelection, CharacterGenerationError]:
        """Select one eligible character before reading character memory."""
        if not character_names:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="No character names were supplied.",
                )
            )
        response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "character_name": types.Schema(
                    type=types.Type.STRING,
                    enum=list(character_names),
                )
            },
            required=["character_name"],
        )
        result = await self._request_json(
            system_instruction=system_instruction,
            user_content=user_content,
            response_schema=response_schema,
        )
        if is_err(result):
            return Err(result.error)
        raw_name = result.value.get("character_name")
        if not isinstance(raw_name, str) or not raw_name.strip():
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini response missing valid 'character_name'.",
                )
            )
        return Ok(CharacterSelection(character_name=raw_name.strip()))

    async def generate(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_name: str,
    ) -> Result[GeneratedCharacterResponse, CharacterGenerationError]:
        """Generate a response after the application selected a character."""
        if not character_name.strip():
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="A character name is required for response generation.",
                )
            )
        response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "content": types.Schema(type=types.Type.STRING),
                **_memory_properties(),
            },
            required=["content"],
        )
        result = await self._request_json(
            system_instruction=system_instruction,
            user_content=user_content,
            response_schema=response_schema,
            mcp_servers=self._mcp_servers.get(character_name, ()),
        )
        if is_err(result):
            return Err(result.error)

        raw_content = result.value.get("content")
        if not isinstance(raw_content, str):
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini response missing valid 'content'.",
                )
            )
        content = raw_content.strip()
        if not content:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.EMPTY_RESPONSE,
                    message="Gemini returned empty response content.",
                )
            )

        try:
            candidates, selection_summary = _memory_values(result.value)
        except ValueError as error:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message=str(error),
                )
            )
        return Ok(
            GeneratedCharacterResponse(
                character_name=character_name.strip(),
                content=content,
                memory_candidates=candidates,
                selection_summary=selection_summary,
            )
        )

    async def generate_times_episode(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_names: tuple[str, ...],
    ) -> Result[tuple[TimesPost, ...], CharacterGenerationError]:
        """Generate zero or more character posts for a Times episode."""
        if not character_names:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="No character names were supplied.",
                )
            )
        response_schema = types.Schema(
            type=types.Type.OBJECT,
            properties={
                "posts": types.Schema(
                    type=types.Type.ARRAY,
                    max_items=MAX_TIMES_POSTS,
                    items=types.Schema(
                        type=types.Type.OBJECT,
                        properties={
                            "character_name": types.Schema(
                                type=types.Type.STRING,
                                enum=list(character_names),
                            ),
                            "content": types.Schema(
                                type=types.Type.STRING,
                                max_length=MAX_TIMES_POST_LENGTH,
                            ),
                            **_memory_properties(),
                        },
                        required=["character_name", "content"],
                    ),
                ),
            },
            required=["posts"],
        )
        result = await self._request_json(
            system_instruction=system_instruction,
            user_content=user_content,
            response_schema=response_schema,
        )
        if is_err(result):
            return Err(result.error)

        raw_posts = result.value.get("posts", [])
        if raw_posts is None:
            raw_posts = []
        if not isinstance(raw_posts, list):
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini response 'posts' must be an array.",
                )
            )
        if len(raw_posts) > MAX_TIMES_POSTS:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini returned too many Times posts.",
                )
            )

        valid_names_map = {name.casefold(): name for name in character_names}
        posts: list[TimesPost] = []
        for item in raw_posts:
            if not isinstance(item, dict):
                return Err(
                    CharacterGenerationError(
                        type=CharacterGenerationErrorType.INVALID_RESPONSE,
                        message="Each post in Gemini response must be an object.",
                    )
                )
            name = item.get("character_name")
            content = item.get("content")
            if not isinstance(name, str) or not isinstance(content, str):
                return Err(
                    CharacterGenerationError(
                        type=CharacterGenerationErrorType.INVALID_RESPONSE,
                        message="Post character_name and content must be strings.",
                    )
                )
            cleaned_name = name.strip()
            canonical_name = valid_names_map.get(cleaned_name.casefold())
            if canonical_name is None:
                return Err(
                    CharacterGenerationError(
                        type=CharacterGenerationErrorType.INVALID_RESPONSE,
                        message=f"Post character_name '{cleaned_name}' is not in the roster.",
                    )
                )
            cleaned_content = content.strip()
            if len(cleaned_content) > MAX_TIMES_POST_LENGTH:
                return Err(
                    CharacterGenerationError(
                        type=CharacterGenerationErrorType.INVALID_RESPONSE,
                        message="Gemini returned an overly long Times post.",
                    )
                )
            if cleaned_content:
                try:
                    candidates, summary = _memory_values(item)
                except ValueError as error:
                    return Err(
                        CharacterGenerationError(
                            type=CharacterGenerationErrorType.INVALID_RESPONSE,
                            message=str(error),
                        )
                    )
                posts.append(
                    TimesPost(
                        character_name=canonical_name,
                        content=cleaned_content,
                        memory_candidates=candidates,
                        selection_summary=summary,
                    )
                )

        return Ok(tuple(posts))
