"""Tests for provider-neutral text generation clients."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.contracts.messages.llm import TextGenerationRequest
from app.contracts.ports.llm import TextGenerationError
from app.infrastructure.llm import gemini as gemini_module
from app.infrastructure.llm import openai as openai_module
from app.infrastructure.llm.gemini import GeminiTextGenerationClient
from app.infrastructure.llm.openai import OpenAITextGenerationClient


def _request(
    *, output_schema: dict[str, object] | None = None
) -> TextGenerationRequest:
    """Build one deterministic request for adapter tests."""
    return TextGenerationRequest(
        system_instruction="Answer as JSON.",
        input_text="What is reusable?",
        output_schema=output_schema,
        schema_name="answer",
        max_output_tokens=123,
    )


@pytest.mark.anyio
async def test_gemini_client_maps_json_generation_and_closes_transports(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Gemini receives the shared request shape and both transports are closed."""
    generate = AsyncMock(return_value=SimpleNamespace(text='{"ok": true}'))
    async_close = AsyncMock()
    sync_close = Mock()
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate),
            aclose=async_close,
        ),
        close=sync_close,
    )
    factory = Mock(return_value=fake_client)
    monkeypatch.setattr(gemini_module.genai, "Client", factory)

    client = GeminiTextGenerationClient("gemini-key", "gemini-model")
    response = await client.generate(
        _request(
            output_schema={
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
            }
        )
    )

    assert response.output_text == '{"ok": true}'
    factory.assert_called_once_with(api_key="gemini-key")
    kwargs = generate.call_args.kwargs
    assert kwargs["model"] == "gemini-model"
    assert kwargs["contents"] == "What is reusable?"
    assert kwargs["config"].system_instruction == "Answer as JSON."
    assert kwargs["config"].response_schema == {
        "type": "object",
        "properties": {"ok": {"type": "boolean"}},
    }

    await client.aclose()
    async_close.assert_awaited_once()
    sync_close.assert_called_once()


@pytest.mark.anyio
async def test_gemini_client_turns_empty_and_transport_failures_into_safe_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Provider details do not escape the shared error boundary."""
    generate = AsyncMock(side_effect=RuntimeError("secret transport detail"))
    fake_client = SimpleNamespace(
        aio=SimpleNamespace(
            models=SimpleNamespace(generate_content=generate),
            aclose=AsyncMock(),
        ),
        close=Mock(),
    )
    monkeypatch.setattr(gemini_module.genai, "Client", Mock(return_value=fake_client))

    client = GeminiTextGenerationClient("gemini-key", "gemini-model")
    with pytest.raises(TextGenerationError, match="Gemini generation failed") as error:
        await client.generate(_request())

    assert "secret" not in str(error.value)


@pytest.mark.anyio
async def test_openai_client_uses_responses_json_schema_and_context_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """OpenAI receives strict JSON output settings through the Responses API."""
    create = AsyncMock(return_value=SimpleNamespace(output_text='{"ok": true}'))
    close = AsyncMock()
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        close=close,
    )
    factory = Mock(return_value=fake_client)
    monkeypatch.setattr(openai_module, "AsyncOpenAI", factory)

    async with OpenAITextGenerationClient("openai-key", "openai-model") as client:
        response = await client.generate(
            _request(
                output_schema={
                    "type": "object",
                    "properties": {"ok": {"type": "boolean"}},
                }
            )
        )

    assert response.output_text == '{"ok": true}'
    factory.assert_called_once_with(api_key="openai-key", timeout=60.0)
    kwargs = create.call_args.kwargs
    assert kwargs["model"] == "openai-model"
    assert kwargs["instructions"] == "Answer as JSON."
    assert kwargs["input"] == "What is reusable?"
    assert kwargs["store"] is False
    assert kwargs["text"] == {
        "format": {
            "type": "json_schema",
            "name": "answer",
            "schema": {
                "type": "object",
                "properties": {"ok": {"type": "boolean"}},
            },
            "strict": True,
        }
    }
    close.assert_awaited_once()


@pytest.mark.anyio
async def test_openai_client_omits_json_format_for_plain_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The reusable client also supports ordinary text generation."""
    create = AsyncMock(return_value=SimpleNamespace(output_text="plain text"))
    fake_client = SimpleNamespace(
        responses=SimpleNamespace(create=create),
        close=AsyncMock(),
    )
    monkeypatch.setattr(openai_module, "AsyncOpenAI", Mock(return_value=fake_client))

    client = OpenAITextGenerationClient("openai-key", "openai-model")
    response = await client.generate(_request())

    assert response.output_text == "plain text"
    assert "text" not in create.call_args.kwargs


def test_generation_configuration_rejects_missing_values() -> None:
    """Adapters and requests fail before an invalid call reaches a provider."""
    with pytest.raises(ValueError, match="API key"):
        GeminiTextGenerationClient(" ", "model")
    with pytest.raises(ValueError, match="model"):
        OpenAITextGenerationClient("key", " ")
    with pytest.raises(ValueError, match="input"):
        TextGenerationRequest(system_instruction="", input_text=" ")
    with pytest.raises(ValueError, match="schema"):
        TextGenerationRequest(
            system_instruction="instruction",
            input_text="input",
            output_schema={},
        )
