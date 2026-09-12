"""Gemini SDK adapter for character selection and response generation."""

import asyncio
import json
import logging
from dataclasses import replace
from typing import Any

from flow_res import Err, Ok, Result, is_err
from google import genai
from google.genai import types

from app.contracts.messages import (
    CharacterSelection,
    CharacterWorkRequest,
    GeneratedCharacterResponse,
    TimesPost,
    TimesWorkIntent,
)
from app.contracts.ports.character_response_generator import (
    CharacterGenerationError,
    CharacterGenerationErrorType,
    CharacterWorkTool,
    ICharacterResponseGenerator,
)
from app.domain.character_memory import (
    MAX_CHARACTER_MEMORY_LENGTH,
    MAX_CHARACTER_MEMORY_SUMMARY_LENGTH,
)

logger = logging.getLogger(__name__)
GENERATION_TIMEOUT_SECONDS = 60.0
WORK_TOOL_TIMEOUT_SECONDS = 20.0
MAX_MEMORY_CANDIDATES = 8
MAX_TIMES_POSTS = 12
MAX_TIMES_POST_LENGTH = 4000
MAX_TIMES_WORK_INTENTS = 1
MAX_TIMES_WORK_OBJECTIVE_LENGTH = 2000
MAX_TIMES_WORK_CONTEXT_LENGTH = 4000
MAX_TIMES_WORK_CRITERION_LENGTH = 500
MAX_TIMES_WORK_CRITERIA = 8
WORK_TOOL_NAME = "request_character_work"


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


def _times_work_intent_schema(
    character_names: tuple[str, ...],
) -> types.Schema:
    """Build the shallow, episode-level schema for one Times commitment."""
    return types.Schema(
        type=types.Type.OBJECT,
        properties={
            "character_name": types.Schema(
                type=types.Type.STRING,
                enum=list(character_names),
            ),
            "objective": types.Schema(
                type=types.Type.STRING,
                max_length=MAX_TIMES_WORK_OBJECTIVE_LENGTH,
            ),
            "context": types.Schema(
                type=types.Type.STRING,
                max_length=MAX_TIMES_WORK_CONTEXT_LENGTH,
            ),
            "success_criteria": types.Schema(
                type=types.Type.ARRAY,
                max_items=MAX_TIMES_WORK_CRITERIA,
                items=types.Schema(
                    type=types.Type.STRING,
                    max_length=MAX_TIMES_WORK_CRITERION_LENGTH,
                ),
            ),
        },
        required=["character_name", "objective"],
    )


def _times_response_schema(
    character_names: tuple[str, ...], *, include_work_intent: bool
) -> types.Schema:
    """Build the Times response schema without deeply nesting work metadata."""
    post_properties: dict[str, types.Schema] = {
        "character_name": types.Schema(
            type=types.Type.STRING,
            enum=list(character_names),
        ),
        "content": types.Schema(
            type=types.Type.STRING,
            max_length=MAX_TIMES_POST_LENGTH,
        ),
        **_memory_properties(),
    }
    properties: dict[str, types.Schema] = {
        "posts": types.Schema(
            type=types.Type.ARRAY,
            max_items=MAX_TIMES_POSTS,
            items=types.Schema(
                type=types.Type.OBJECT,
                properties=post_properties,
                required=["character_name", "content"],
            ),
        )
    }
    if include_work_intent:
        properties["work_intent"] = _times_work_intent_schema(character_names)
    return types.Schema(
        type=types.Type.OBJECT,
        properties=properties,
        required=["posts"],
    )


def _work_tool(character_names: tuple[str, ...]) -> types.Tool:
    """Build the client-side tool used by a character's normal response."""
    parameters = types.Schema(
        type=types.Type.OBJECT,
        properties={
            "character_name": types.Schema(
                type=types.Type.STRING,
                enum=list(character_names),
                description="依頼を担当する登録キャラクター名",
            ),
            "objective": types.Schema(
                type=types.Type.STRING,
                max_length=MAX_TIMES_WORK_OBJECTIVE_LENGTH,
                description="実行する具体的な調査・実装・検証の目的",
            ),
            "context": types.Schema(
                type=types.Type.STRING,
                max_length=MAX_TIMES_WORK_CONTEXT_LENGTH,
                description="依頼の背景や追加条件",
            ),
        },
        required=["character_name", "objective"],
    )
    return types.Tool(
        function_declarations=[
            types.FunctionDeclaration(
                name=WORK_TOOL_NAME,
                description=(
                    "明確な依頼に対して、指定キャラクターのCodex作業を開始または継続する。"
                ),
                parameters=parameters,
            )
        ]
    )


def _parse_work_request(
    call: types.FunctionCall,
    character_names: tuple[str, ...],
) -> Result[CharacterWorkRequest, CharacterGenerationError]:
    """Validate one model tool call before it crosses the application boundary."""
    if call.name != WORK_TOOL_NAME or not isinstance(call.args, dict):
        return Err(
            CharacterGenerationError(
                type=CharacterGenerationErrorType.INVALID_RESPONSE,
                message="Gemini returned an unsupported work function call.",
            )
        )
    raw_name = call.args.get("character_name")
    raw_objective = call.args.get("objective")
    raw_context = call.args.get("context", "")
    valid_names = {name.casefold(): name for name in character_names}
    canonical_name = (
        valid_names.get(raw_name.strip().casefold())
        if isinstance(raw_name, str)
        else None
    )
    if (
        canonical_name is None
        or not isinstance(raw_objective, str)
        or not isinstance(raw_context, str)
    ):
        return Err(
            CharacterGenerationError(
                type=CharacterGenerationErrorType.INVALID_RESPONSE,
                message="Gemini returned invalid work function arguments.",
            )
        )
    objective = raw_objective.strip()
    context = raw_context.strip()
    if (
        not objective
        or len(objective) > MAX_TIMES_WORK_OBJECTIVE_LENGTH
        or len(context) > MAX_TIMES_WORK_CONTEXT_LENGTH
    ):
        return Err(
            CharacterGenerationError(
                type=CharacterGenerationErrorType.INVALID_RESPONSE,
                message="Gemini returned an empty or oversized work request.",
            )
        )
    return Ok(
        CharacterWorkRequest(
            character_name=canonical_name,
            objective=objective,
            context=context,
        )
    )


class GeminiCharacterResponseGenerator(ICharacterResponseGenerator):
    """Generate structured character selections and responses with Gemini."""

    def __init__(
        self,
        client: genai.Client,
        model: str,
        *,
        max_output_tokens: int = 4096,
    ) -> None:
        """Initialize the Gemini character response generator.

        Args:
            client: The Google GenAI client instance.
            model: The Gemini model identifier to use (e.g., 'gemini-2.5-flash').
            max_output_tokens: Maximum number of output tokens to generate.
        """
        self._client = client
        self._model = model
        self._max_output_tokens = max_output_tokens

    async def aclose(self) -> None:
        """Close the synchronous and asynchronous GenAI clients."""
        try:
            await self._client.aio.aclose()
        finally:
            self._client.close()

    async def _generate_content(
        self,
        *,
        contents: Any,
        config: types.GenerateContentConfig,
    ) -> Result[types.GenerateContentResponse, CharacterGenerationError]:
        """Call Gemini once and validate the transport-level response."""
        try:
            async with asyncio.timeout(GENERATION_TIMEOUT_SECONDS):
                response = await self._client.aio.models.generate_content(
                    model=self._model,
                    contents=contents,
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
            return Ok(response)
        except asyncio.CancelledError:
            raise
        except Exception as err:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.GENERATION_FAILED,
                    message=f"Gemini response generation failed: {err}",
                )
            )

    @staticmethod
    def _decode_json(
        response: types.GenerateContentResponse,
    ) -> Result[dict[str, Any], CharacterGenerationError]:
        """Parse one structured JSON response after transport validation."""
        text = response.text

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

    async def _request_json(
        self,
        *,
        system_instruction: str,
        user_content: str,
        response_schema: types.Schema,
    ) -> Result[dict[str, Any], CharacterGenerationError]:
        """Call Gemini and parse one structured JSON object."""
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_schema=response_schema,
        )
        response = await self._generate_content(contents=user_content, config=config)
        if is_err(response):
            return Err(response.error)
        return self._decode_json(response.value)

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

    async def _request_json_with_work_tool(
        self,
        *,
        system_instruction: str,
        user_content: str,
        response_schema: types.Schema,
        character_names: tuple[str, ...],
        work_tool: CharacterWorkTool,
    ) -> Result[dict[str, Any], CharacterGenerationError]:
        """Generate a response and execute at most one client-side work tool call."""
        if not character_names:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="No character names were supplied for the work tool.",
                )
            )
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_schema=response_schema,
            tools=[_work_tool(character_names)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.AUTO,
                )
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        response = await self._generate_content(contents=user_content, config=config)
        if is_err(response):
            return Err(response.error)
        calls = list(response.value.function_calls or [])
        if not calls:
            return self._decode_json(response.value)
        if len(calls) != 1:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini returned too many work function calls.",
                )
            )
        call = calls[0]
        if not isinstance(call.name, str):
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini returned a work function without a name.",
                )
            )
        request = _parse_work_request(call, character_names)
        if is_err(request):
            return Err(request.error)
        try:
            async with asyncio.timeout(WORK_TOOL_TIMEOUT_SECONDS):
                tool_result = await work_tool(request.value)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Character work tool callback failed")
            tool_result = json.dumps(
                {"status": "error", "message": "作業の受付に失敗しました。"},
                ensure_ascii=False,
            )

        candidates = response.value.candidates or []
        if not candidates or candidates[0].content is None:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Gemini work response did not include a tool trace.",
                )
            )
        function_response = types.FunctionResponse(
            name=call.name,
            response={"result": tool_result},
            id=call.id,
        )
        follow_up_contents = [
            types.Content(
                role="user",
                parts=[types.Part.from_text(text=user_content)],
            ),
            candidates[0].content,
            types.Content(
                role="user",
                parts=[types.Part(function_response=function_response)],
            ),
        ]
        follow_up_config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            max_output_tokens=self._max_output_tokens,
            response_mime_type="application/json",
            response_schema=response_schema,
            tools=[_work_tool(character_names)],
            tool_config=types.ToolConfig(
                function_calling_config=types.FunctionCallingConfig(
                    mode=types.FunctionCallingConfigMode.NONE,
                )
            ),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(
                disable=True
            ),
        )
        final_response = await self._generate_content(
            contents=follow_up_contents,
            config=follow_up_config,
        )
        if is_err(final_response):
            return Err(final_response.error)
        return self._decode_json(final_response.value)

    async def generate(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_name: str,
        work_tool: CharacterWorkTool | None = None,
        work_character_names: tuple[str, ...] = (),
    ) -> Result[GeneratedCharacterResponse, CharacterGenerationError]:
        """Generate a response for the selected character."""
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
        if work_tool is None:
            result = await self._request_json(
                system_instruction=system_instruction,
                user_content=user_content,
                response_schema=response_schema,
            )
        else:
            names = work_character_names or (character_name.strip(),)
            result = await self._request_json_with_work_tool(
                system_instruction=system_instruction,
                user_content=user_content,
                response_schema=response_schema,
                character_names=names,
                work_tool=work_tool,
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
        result = await self._request_json(
            system_instruction=system_instruction,
            user_content=user_content,
            response_schema=_times_response_schema(
                character_names, include_work_intent=True
            ),
        )
        if is_err(result) and _is_schema_rejection(result.error):
            logger.warning("Retrying Times generation with a flat posts schema")
            result = await self._request_json(
                system_instruction=system_instruction,
                user_content=user_content,
                response_schema=_times_response_schema(
                    character_names, include_work_intent=False
                ),
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
                        message=(
                            f"Post character_name '{cleaned_name}' is not in the roster."
                        ),
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
            if not cleaned_content:
                continue
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

        work_intent = _parse_times_work_intent(
            result.value.get("work_intent"), valid_names_map
        )
        if work_intent is None and "work_intent" not in result.value:
            work_intent = _parse_legacy_times_work_intent(raw_posts, valid_names_map)
        if isinstance(work_intent, CharacterGenerationError):
            return Err(work_intent)
        if work_intent is None:
            return Ok(tuple(posts))
        if not posts:
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="A work intent requires visible Times content.",
                )
            )
        if not any(post.character_name == work_intent.character_name for post in posts):
            return Err(
                CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message=(
                        "A work intent must belong to a character with visible Times content."
                    ),
                )
            )
        attached = False
        normalized_posts: list[TimesPost] = []
        for post in posts:
            if not attached and post.character_name == work_intent.character_name:
                normalized_posts.append(replace(post, work_intents=(work_intent,)))
                attached = True
            else:
                normalized_posts.append(post)
        return Ok(tuple(normalized_posts))


def _is_schema_rejection(error: CharacterGenerationError) -> bool:
    """Return whether Gemini rejected the response schema itself."""
    return error.type is CharacterGenerationErrorType.GENERATION_FAILED and (
        "400" in error.message and "invalid_argument" in error.message.lower()
    )


def _parse_times_work_intent(
    raw_intent: object,
    valid_names_map: dict[str, str],
) -> TimesWorkIntent | CharacterGenerationError | None:
    """Validate the single shallow work intent returned beside Times posts."""
    if raw_intent is None:
        return None
    if not isinstance(raw_intent, dict):
        return CharacterGenerationError(
            type=CharacterGenerationErrorType.INVALID_RESPONSE,
            message="Gemini response 'work_intent' must be an object.",
        )
    raw_name = raw_intent.get("character_name")
    objective = raw_intent.get("objective")
    context = raw_intent.get("context", "")
    criteria = raw_intent.get("success_criteria", [])
    if (
        not isinstance(raw_name, str)
        or not isinstance(objective, str)
        or not isinstance(context, str)
        or not isinstance(criteria, list)
        or not all(isinstance(item, str) for item in criteria)
    ):
        return CharacterGenerationError(
            type=CharacterGenerationErrorType.INVALID_RESPONSE,
            message="Work intent fields have invalid types.",
        )
    canonical_name = valid_names_map.get(raw_name.strip().casefold())
    if canonical_name is None:
        return CharacterGenerationError(
            type=CharacterGenerationErrorType.INVALID_RESPONSE,
            message=(
                f"Work intent character_name '{raw_name.strip()}' is not in the roster."
            ),
        )
    cleaned_objective = objective.strip()
    cleaned_context = context.strip()
    cleaned_criteria = tuple(item.strip() for item in criteria if item.strip())
    if (
        not cleaned_objective
        or len(cleaned_objective) > MAX_TIMES_WORK_OBJECTIVE_LENGTH
        or len(cleaned_context) > MAX_TIMES_WORK_CONTEXT_LENGTH
        or len(cleaned_criteria) > MAX_TIMES_WORK_CRITERIA
        or any(
            len(criterion) > MAX_TIMES_WORK_CRITERION_LENGTH
            for criterion in cleaned_criteria
        )
    ):
        return CharacterGenerationError(
            type=CharacterGenerationErrorType.INVALID_RESPONSE,
            message="Work intent is too long or empty.",
        )
    return TimesWorkIntent(
        intent_id="",
        character_name=canonical_name,
        objective=cleaned_objective,
        context=cleaned_context,
        success_criteria=cleaned_criteria,
    )


def _parse_legacy_times_work_intent(
    raw_posts: list[object],
    valid_names_map: dict[str, str],
) -> TimesWorkIntent | CharacterGenerationError | None:
    """Read the former per-post shape while old plans are still in flight."""
    found: TimesWorkIntent | None = None
    for item in raw_posts:
        if not isinstance(item, dict) or "work_intents" not in item:
            continue
        raw_intents = item.get("work_intents")
        if raw_intents is None:
            raw_intents = []
        if not isinstance(raw_intents, list):
            return CharacterGenerationError(
                type=CharacterGenerationErrorType.INVALID_RESPONSE,
                message="Post work_intents must be an array.",
            )
        if len(raw_intents) > MAX_TIMES_WORK_INTENTS:
            return CharacterGenerationError(
                type=CharacterGenerationErrorType.INVALID_RESPONSE,
                message="Gemini returned too many work intents.",
            )
        for raw_intent in raw_intents:
            parsed = _parse_times_work_intent(raw_intent, valid_names_map)
            if isinstance(parsed, CharacterGenerationError):
                return parsed
            if parsed is None:
                continue
            if found is not None:
                return CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="Only one work intent may be created per Times episode.",
                )
            content = item.get("content")
            if not isinstance(content, str) or not content.strip():
                return CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message="A work intent requires visible Times content.",
                )
            speaker = item.get("character_name")
            if (
                not isinstance(speaker, str)
                or valid_names_map.get(speaker.strip().casefold())
                != parsed.character_name
            ):
                return CharacterGenerationError(
                    type=CharacterGenerationErrorType.INVALID_RESPONSE,
                    message=(
                        "A work intent must belong to the character making the commitment."
                    ),
                )
            found = parsed
    return found
