"""Tests for character orchestration over the shared text client."""

from datetime import UTC, datetime

import pytest
from flow_res import is_err

from app.contracts.messages.character_prompt import (
    CharacterConversationMessage,
    CharacterSelectionContext,
)
from app.contracts.messages.llm import TextGenerationRequest, TextGenerationResponse
from app.contracts.ports.llm import ITextGenerationClient, TextGenerationError
from app.domain.characters import CharacterDefinition, CharacterRoster
from app.infrastructure.characters import CharacterResponseGenerator


def _character(character_id: str, name: str) -> CharacterDefinition:
    """Build a small character definition for generator tests."""
    return CharacterDefinition(
        character_id=character_id,
        name=name,
        position="担当",
        responsibilities=("会話",),
        persona=f"{name}の人格",
        speech_style="短く話す",
    )


def _message(content: str) -> CharacterConversationMessage:
    """Build one aware conversation message."""
    return CharacterConversationMessage(
        message_id="message-1",
        author_id="master-1",
        author_name="Master",
        author_kind="user",
        occurred_at=datetime(2026, 9, 14, tzinfo=UTC),
        content=content,
    )


def _selection_context() -> CharacterSelectionContext:
    """Build a two-character selection snapshot."""
    return CharacterSelectionContext(
        roster=CharacterRoster(
            ("共通ルール",),
            (_character("alice", "Alice"), _character("bob", "Bob")),
        ),
        current=_message("相談です"),
    )


class StubTextGenerationClient(ITextGenerationClient):
    """Return prepared responses and record the provider-neutral requests."""

    def __init__(self, *outputs: str) -> None:
        self._outputs = list(outputs)
        self.requests: list[TextGenerationRequest] = []
        self.closed = False

    async def generate(self, request: TextGenerationRequest) -> TextGenerationResponse:
        """Return the next prepared JSON response."""
        self.requests.append(request)
        return TextGenerationResponse(self._outputs.pop(0))

    async def aclose(self) -> None:
        """Record closure."""
        self.closed = True


@pytest.mark.anyio
async def test_character_generator_uses_ids_and_shared_context_for_both_operations() -> (
    None
):
    """Selection and generation share stable IDs and provider-neutral snapshots."""
    client = StubTextGenerationClient(
        '{"character_id":"alice"}',
        '{"character_id":"alice","content":" 返答です。",'
        '"memory_candidates":["好きな話題"],"selection_summary":""}',
    )
    generator = CharacterResponseGenerator(client)
    selection_context = _selection_context()

    selected = await generator.select_character(selection_context)
    assert not is_err(selected)
    assert selected.value.character_id == "alice"

    generated = await generator.generate(selection_context.for_character("alice"))
    assert not is_err(generated)
    assert generated.value.character_id == "alice"
    assert generated.value.content == "返答です。"
    assert generated.value.memory_candidates == ("好きな話題",)
    assert generated.value.selection_summary is None

    assert len(client.requests) == 2
    assert client.requests[0].schema_name == "character_selection"
    assert client.requests[1].schema_name == "character_response"
    assert '"master": null' in client.requests[0].input_text
    assert "共通ルール" in client.requests[1].system_instruction

    await generator.aclose()
    assert client.closed is True


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("output", "message"),
    [
        ('{"character_id":"unknown"}', "unknown character"),
        ("not-json", "invalid JSON"),
    ],
)
async def test_character_generator_rejects_untrusted_selection_output(
    output: str,
    message: str,
) -> None:
    """Model output cannot select outside the configured roster or bypass JSON."""
    generator = CharacterResponseGenerator(StubTextGenerationClient(output))

    result = await generator.select_character(_selection_context())

    assert is_err(result)
    assert result.error.type.name == "INVALID_RESPONSE"
    assert message in result.error.message


@pytest.mark.anyio
async def test_character_generator_classifies_provider_failures() -> None:
    """Provider failures become the existing character generation error contract."""

    class FailingClient(ITextGenerationClient):
        """Raise a provider error for one request."""

        async def generate(
            self, request: TextGenerationRequest
        ) -> TextGenerationResponse:
            """Raise a safe provider failure."""
            del request
            raise TextGenerationError("provider unavailable")

        async def aclose(self) -> None:
            """There are no resources in this fake client."""

    result = await CharacterResponseGenerator(FailingClient()).select_character(
        _selection_context()
    )

    assert is_err(result)
    assert result.error.type.name == "GENERATION_FAILED"
    assert result.error.message == "provider unavailable"


@pytest.mark.anyio
async def test_character_generator_rejects_unbounded_memory_candidates() -> None:
    """A provider cannot use memory candidates to bypass the output limit."""
    output = (
        '{"character_id":"alice","content":"返答",'
        '"memory_candidates":['
        + ",".join('"memory"' for _ in range(9))
        + '],"selection_summary":""}'
    )
    generator = CharacterResponseGenerator(StubTextGenerationClient(output))

    result = await generator.generate(_selection_context().for_character("alice"))

    assert is_err(result)
    assert result.error.type.name == "INVALID_RESPONSE"
