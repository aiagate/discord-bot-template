"""Tests for GeminiCharacterResponseGenerator."""

import asyncio
import json
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from flow_res import is_err, is_ok
from google import genai
from google.genai import types

from app.contracts.messages import CharacterSelection, GeneratedCharacterResponse
from app.contracts.ports.character_response_generator import (
    CharacterGenerationErrorType,
)
from app.domain.character_memory import MAX_CHARACTER_MEMORY_SUMMARY_LENGTH
from app.infrastructure.gemini import GeminiCharacterResponseGenerator


def _create_mock_client() -> tuple[MagicMock, AsyncMock]:
    """Create a mock genai.Client with a mock aio.models.generate_content method."""
    mock_client = MagicMock(spec=genai.Client)
    mock_generate = AsyncMock()
    mock_client.aio.models.generate_content = mock_generate
    return mock_client, mock_generate


@pytest.mark.anyio
async def test_select_character_success() -> None:
    """Selection returns one eligible character and configures a JSON enum."""
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps(
        {
            "character_name": "Dorothy",
        }
    )
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    result = await generator.select_character(
        system_instruction="あなたはメイドです。",
        user_content="こんにちは",
        character_names=("Dorothy", "Eris"),
    )

    assert is_ok(result)
    assert result.value == CharacterSelection(character_name="Dorothy")

    mock_generate.assert_awaited_once()
    await_args = mock_generate.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["model"] == "gemini-2.5-flash"
    assert kwargs["contents"] == "こんにちは"
    assert isinstance(kwargs["config"], types.GenerateContentConfig)
    config = kwargs["config"]
    assert config.system_instruction == "あなたはメイドです。"
    assert config.max_output_tokens == 4096
    assert config.response_mime_type == "application/json"
    assert isinstance(config.response_schema, types.Schema)
    assert config.response_schema.properties is not None
    character_schema = config.response_schema.properties["character_name"]
    assert isinstance(character_schema, types.Schema)
    assert character_schema.enum == ["Dorothy", "Eris"]


@pytest.mark.anyio
async def test_generate_success_and_custom_max_output_tokens() -> None:
    """Config respects the custom max_output_tokens passed to constructor."""
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps(
        {
            "content": "応答テキスト",
            "memory_candidates": ["ユーザーは朝に作業する。"],
            "selection_summary": "ユーザーは朝に作業する。",
        }
    )
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
        max_output_tokens=512,
    )

    result = await generator.generate(
        system_instruction="システム指示",
        user_content="テスト入力",
        character_name="Eris",
    )

    assert is_ok(result)
    assert result.value == GeneratedCharacterResponse(
        character_name="Eris",
        content="応答テキスト",
        memory_candidates=("ユーザーは朝に作業する。",),
        selection_summary="ユーザーは朝に作業する。",
    )
    await_args = mock_generate.await_args
    assert await_args is not None
    kwargs = await_args.kwargs
    assert kwargs["config"].max_output_tokens == 512
    assert (
        kwargs["config"].response_schema.properties["content"].type == types.Type.STRING
    )
    summary_schema = kwargs["config"].response_schema.properties["selection_summary"]
    assert summary_schema.max_length == MAX_CHARACTER_MEMORY_SUMMARY_LENGTH


@pytest.mark.anyio
async def test_aclose_closes_genai_clients() -> None:
    """Closing the generator closes both GenAI client transports."""
    mock_client, _ = _create_mock_client()
    mock_client.aio.aclose = AsyncMock()

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    await generator.aclose()

    mock_client.aio.aclose.assert_awaited_once_with()
    mock_client.close.assert_called_once_with()


@pytest.mark.anyio
async def test_aclose_closes_sync_client_when_async_close_fails() -> None:
    """Sync client cleanup runs even if async client cleanup fails."""
    mock_client, _ = _create_mock_client()
    mock_client.aio.aclose = AsyncMock(side_effect=RuntimeError("cleanup failed"))

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await generator.aclose()

    mock_client.close.assert_called_once_with()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "empty_text",
    [
        None,
        "",
        "   ",
        "\n\t  \n",
    ],
)
async def test_generate_empty_response_returns_err(empty_text: str | None) -> None:
    """Empty or whitespace-only response text returns EMPTY_RESPONSE error."""
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = empty_text
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    result = await generator.generate(
        system_instruction="システム指示",
        user_content="入力",
        character_name="Dorothy",
    )

    assert is_err(result)
    assert result.error.type == CharacterGenerationErrorType.EMPTY_RESPONSE


@pytest.mark.anyio
@pytest.mark.parametrize(
    "invalid_json_text",
    [
        "not json at all",
        "{invalid json}",
        "[]",
        json.dumps({}),
        json.dumps({"content": 456}),
        json.dumps({"content": "hello", "memory_candidates": 123}),
        json.dumps({"content": "hello", "memory_candidates": [123]}),
        json.dumps({"content": "hello", "memory_candidates": ["x" * 501]}),
        json.dumps({"content": "hello", "selection_summary": 123}),
        json.dumps({"content": "hello", "selection_summary": "x" * 401}),
    ],
)
async def test_generate_invalid_json_returns_invalid_response_err(
    invalid_json_text: str,
) -> None:
    """Malformed JSON or missing required fields returns INVALID_RESPONSE error."""
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = invalid_json_text
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    result = await generator.generate(
        system_instruction="システム指示",
        user_content="入力",
        character_name="Dorothy",
    )

    assert is_err(result)
    assert result.error.type == CharacterGenerationErrorType.INVALID_RESPONSE


@pytest.mark.anyio
async def test_generate_empty_content_field_returns_empty_response_err() -> None:
    """Empty content string inside JSON returns EMPTY_RESPONSE error."""
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps({"character_name": "Dorothy", "content": "   "})
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    result = await generator.generate(
        system_instruction="システム指示",
        user_content="入力",
        character_name="Dorothy",
    )

    assert is_err(result)
    assert result.error.type == CharacterGenerationErrorType.EMPTY_RESPONSE


@pytest.mark.anyio
async def test_generate_api_failure_returns_err() -> None:
    """Exceptions from the SDK call return GENERATION_FAILED error."""
    mock_client, mock_generate = _create_mock_client()
    mock_generate.side_effect = RuntimeError("API service unavailable")

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    result = await generator.generate(
        system_instruction="システム指示",
        user_content="入力",
        character_name="Dorothy",
    )

    assert is_err(result)
    assert result.error.type == CharacterGenerationErrorType.GENERATION_FAILED
    assert "API service unavailable" in result.error.message


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,expected_attempts,success",
    [(503, 2, True), (429, 2, True), (400, 1, False)],
)
async def test_sdk_retries_only_transient_errors(
    status: int, expected_attempts: int, success: bool
) -> None:
    """Exercise the real SDK's HTTP retries against a local transport."""
    attempts = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return httpx.Response(
                status, json={"error": {"code": status, "message": "test"}}
            )
        return httpx.Response(
            200,
            json={
                "candidates": [
                    {
                        "content": {
                            "parts": [
                                {
                                    "text": json.dumps(
                                        {
                                            "character_name": "Dorothy",
                                            "content": "再試行後の応答",
                                        }
                                    )
                                }
                            ]
                        },
                        "finishReason": "STOP",
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as transport:
        client = genai.Client(
            api_key="local-test-key",
            http_options=types.HttpOptions(
                timeout=20_000,
                httpx_async_client=transport,
                retry_options=types.HttpRetryOptions(
                    attempts=3, initial_delay=0.001, max_delay=0.002, jitter=0
                ),
            ),
        )
        generator = GeminiCharacterResponseGenerator(
            client=client, model="gemini-3.8-flash"
        )
        try:
            result = await generator.generate(
                system_instruction="システム指示",
                user_content="入力",
                character_name="Dorothy",
            )
        finally:
            await generator.aclose()
    assert is_ok(result) is success
    assert attempts == expected_attempts


@pytest.mark.anyio
async def test_generation_has_an_overall_deadline(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An SDK request that never finishes cannot occupy the worker indefinitely."""
    client, generate = _create_mock_client()

    async def hang(**_: object) -> None:
        await asyncio.Event().wait()

    generate.side_effect = hang
    monkeypatch.setattr(
        "app.infrastructure.gemini.character_response_generator.GENERATION_TIMEOUT_SECONDS",
        0.01,
    )
    generator = GeminiCharacterResponseGenerator(client=client, model="test")
    async with asyncio.timeout(1):
        result = await generator.generate(
            system_instruction="test", user_content="test", character_name="Dorothy"
        )
    assert is_err(result)
    assert result.error.type == CharacterGenerationErrorType.GENERATION_FAILED


@pytest.mark.anyio
async def test_truncated_generation_is_not_published_as_a_complete_response() -> None:
    client, generate = _create_mock_client()
    generate.return_value = types.GenerateContentResponse(
        candidates=[
            types.Candidate(
                finish_reason=types.FinishReason.MAX_TOKENS,
                content=types.Content(
                    parts=[
                        types.Part(
                            text=json.dumps(
                                {"character_name": "Dorothy", "content": "途中まで"}
                            )
                        )
                    ]
                ),
            )
        ],
    )
    result = await GeminiCharacterResponseGenerator(client, "test").generate(
        system_instruction="test", user_content="test", character_name="Dorothy"
    )
    assert is_err(result)
    assert result.error.type == CharacterGenerationErrorType.INVALID_RESPONSE


@pytest.mark.anyio
async def test_generate_cancelled_error_propagates() -> None:
    """asyncio.CancelledError is never swallowed and propagates up."""
    mock_client, mock_generate = _create_mock_client()
    mock_generate.side_effect = asyncio.CancelledError()

    generator = GeminiCharacterResponseGenerator(
        client=mock_client,
        model="gemini-2.5-flash",
    )

    with pytest.raises(asyncio.CancelledError):
        await generator.generate(
            system_instruction="システム指示",
            user_content="入力",
            character_name="Dorothy",
        )


@pytest.mark.anyio
async def test_generate_times_episode_success() -> None:
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps(
        {
            "posts": [
                {"character_name": "Dorothy", "content": "お帰りなさいませ。"},
                {"character_name": "Eris", "content": "待っていたぞ。"},
            ]
        }
    )
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(client=mock_client, model="test")
    res = await generator.generate_times_episode(
        system_instruction="test instruction",
        user_content="test input",
        character_names=("Dorothy", "Eris"),
    )
    assert is_ok(res)
    assert len(res.value) == 2
    assert res.value[0].character_name == "Dorothy"
    assert res.value[0].content == "お帰りなさいませ。"
    assert res.value[1].character_name == "Eris"
    assert res.value[1].content == "待っていたぞ。"


@pytest.mark.anyio
async def test_generate_times_episode_empty_posts() -> None:
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps({"posts": []})
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(client=mock_client, model="test")
    res = await generator.generate_times_episode(
        system_instruction="test instruction",
        user_content="test input",
        character_names=("Dorothy", "Eris"),
    )
    assert is_ok(res)
    assert res.value == ()


@pytest.mark.anyio
async def test_generate_times_episode_invalid_character() -> None:
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps(
        {
            "posts": [
                {"character_name": "UnknownMaid", "content": "Hello"},
            ]
        }
    )
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(client=mock_client, model="test")
    res = await generator.generate_times_episode(
        system_instruction="test instruction",
        user_content="test input",
        character_names=("Dorothy", "Eris"),
    )
    assert is_err(res)
    assert res.error.type == CharacterGenerationErrorType.INVALID_RESPONSE
    assert "not in the roster" in res.error.message


@pytest.mark.anyio
async def test_generate_times_episode_rejects_unbounded_output() -> None:
    mock_client, mock_generate = _create_mock_client()
    mock_response = MagicMock(spec=types.GenerateContentResponse)
    mock_response.candidates = []
    mock_response.usage_metadata = None
    mock_response.text = json.dumps(
        {
            "posts": [
                {"character_name": "Dorothy", "content": str(index)}
                for index in range(13)
            ]
        }
    )
    mock_generate.return_value = mock_response

    generator = GeminiCharacterResponseGenerator(client=mock_client, model="test")
    res = await generator.generate_times_episode(
        system_instruction="test instruction",
        user_content="test input",
        character_names=("Dorothy",),
    )

    assert is_err(res)
    assert res.error.type == CharacterGenerationErrorType.INVALID_RESPONSE
    assert "too many" in res.error.message
