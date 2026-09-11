"""Character responses use the correct author and history snapshot."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, Ok, is_err, is_ok

from app.application.character_settings import load_ai_maid_definitions
from app.contracts.messages import CharacterSelection, GeneratedCharacterResponse
from app.contracts.ports import (
    CharacterGenerationError,
    CharacterGenerationErrorType,
    ICharacterMemoryStore,
    ICharacterResponseGenerator,
    IChatHistoryQuery,
    ISpeechPublisher,
    IUnitOfWork,
    SpeechPublishError,
    SpeechPublishErrorType,
)
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.character_memory import CharacterMemory, CharacterMemorySummary
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import (
    AuthorKind,
    DiscordConversationScope,
    MessageContent,
)
from app.usecases.chat.generate_character_response import (
    GenerateCharacterResponseCommand,
    GenerateCharacterResponseHandler,
)
from app.usecases.result import ErrorType, UseCaseError

SCOPE = DiscordConversationScope(guild_id="456", channel_id="123")


def _source(*, author: str = "alice", content: str = "私の依頼は？") -> ChatMessage:
    return ChatMessage.create_discord(
        guild_id=SCOPE.guild_id,
        channel_id=SCOPE.channel_id,
        external_sender_id=author,
        author_name=author.title(),
        external_message_id="123456789012345678",
        content=MessageContent.text(content),
        occurred_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
    )


def _handler(
    source: ChatMessage | None = None,
    *,
    character: str = "Dorothy",
    content: str = "状況を整理しました。",
) -> tuple[
    GenerateCharacterResponseHandler,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    MagicMock,
    GenerateCharacterResponseCommand,
]:
    source = source or _source()
    generator = MagicMock(spec=ICharacterResponseGenerator)
    generator.select_character = AsyncMock(
        return_value=Ok(CharacterSelection(character_name=character))
    )
    generator.generate = AsyncMock(
        return_value=Ok(
            GeneratedCharacterResponse(character_name=character, content=content)
        )
    )
    publisher = MagicMock(spec=ISpeechPublisher)
    publisher.resume = AsyncMock(return_value=Ok(False))
    publisher.publish = AsyncMock(return_value=Ok(None))
    history = MagicMock(spec=IChatHistoryQuery)
    history.get_recent_history = AsyncMock(return_value=Ok([]))
    memory = MagicMock(spec=ICharacterMemoryStore)
    memory.get_selection_summaries = AsyncMock(return_value=Ok({}))
    memory.get_relevant = AsyncMock(return_value=Ok([]))
    memory.save = AsyncMock(return_value=Ok(None))
    memory.save_selection_summary = AsyncMock(return_value=Ok(None))
    repository = MagicMock()
    repository.get_by_id = AsyncMock(return_value=Ok(source))
    uow = MagicMock(spec=IUnitOfWork)
    uow.GetRepository.return_value = repository
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)
    command = GenerateCharacterResponseCommand(
        content=str(source.content.payload["text"]),
        guild_id=SCOPE.guild_id,
        channel_id=SCOPE.channel_id,
        source_message_id=source.id.to_primitive(),
        delivery_channel_id=SCOPE.channel_id,
    )
    return (
        GenerateCharacterResponseHandler(
            generator, publisher, history, memory, uow, load_ai_maid_definitions()
        ),
        generator,
        publisher,
        history,
        memory,
        uow,
        command,
    )


@pytest.mark.anyio
async def test_generates_with_current_author_and_publishes_correct_identity() -> None:
    source = _source()
    handler, generator, publisher, history, memory, uow, command = _handler(source)
    command = replace(command, delivery_channel_id="parent-channel")
    result = await handler.handle(command)

    assert is_ok(result)
    publisher.resume.assert_awaited_once_with(
        SCOPE, source.external_message_id, "parent-channel"
    )
    history.get_recent_history.assert_awaited_once_with(
        SCOPE, limit=20, before=(source.occurred_at, source.id.to_primitive())
    )
    generator.select_character.assert_awaited_once()
    memory.get_relevant.assert_awaited_once_with(
        character_id="dorothy",
        limit=20,
        before=(source.occurred_at, source.id.to_primitive()),
    )
    payload = json.loads(generator.generate.await_args.kwargs["user_content"])
    assert generator.generate.await_args.kwargs["character_name"] == "Dorothy"
    assert payload["character_memory"] == []
    assert payload["current"]["author_id"] == "alice"
    assert payload["current"]["author_name"] == "Alice"
    assert payload["current"]["author_kind"] == "user"
    assert payload["current"]["message_id"] == source.external_message_id
    assert payload["history"] == []
    speech = publisher.publish.await_args.args[0]
    assert speech.username == "Dorothy"
    assert speech.source_message_id == source.external_message_id
    assert speech.conversation_scope == SCOPE
    assert speech.delivery_channel_id == "parent-channel"
    assert "seed=Dorothy" in speech.avatar_url
    uow.GetRepository.return_value.add.assert_not_called()


@pytest.mark.anyio
async def test_selected_character_receives_only_its_character_memory() -> None:
    source = _source()
    handler, generator, _, _, memory, _, command = _handler(source)
    memory_item = CharacterMemory(
        character_id="Dorothy",
        source_message_id="memory-source",
        sequence=0,
        content="ユーザーは朝に作業する。",
        observed_at=source.occurred_at,
    )
    memory.get_relevant.return_value = Ok([memory_item])

    assert is_ok(await handler.handle(command))

    payload = json.loads(generator.generate.await_args.kwargs["user_content"])
    assert payload["character_memory"] == [
        {
            "content": "ユーザーは朝に作業する。",
            "observed_at": source.occurred_at.isoformat(),
        }
    ]
    assert generator.select_character.await_args.kwargs["user_content"]
    assert (
        "ユーザーは朝に作業する。"
        not in generator.select_character.await_args.kwargs["user_content"]
    )


@pytest.mark.anyio
async def test_character_selection_receives_each_character_working_summary() -> None:
    source = _source()
    handler, generator, _, _, memory, _, command = _handler(source)
    summary = CharacterMemorySummary(
        character_id="dorothy",
        source_message_id="summary-source",
        content="ユーザーは朝に作業する。",
        observed_at=source.occurred_at.replace(minute=59),
    )
    memory.get_selection_summaries.return_value = Ok({"dorothy": summary})

    assert is_ok(await handler.handle(command))

    instruction = generator.select_character.await_args.kwargs["system_instruction"]
    profiles = json.loads(instruction.split("キャラクター一覧:\n", 1)[1])
    by_name = {profile["name"]: profile for profile in profiles}
    assert by_name["Dorothy"]["memory_summary"] == summary.content
    assert by_name["Eris"]["memory_summary"] == ""


@pytest.mark.anyio
async def test_generated_selection_summary_is_saved_for_the_next_selection() -> None:
    source = _source()
    handler, generator, _, _, memory, _, command = _handler(source)
    generator.generate.return_value = Ok(
        GeneratedCharacterResponse(
            character_name="Dorothy",
            content="承知しました。",
            selection_summary="ユーザーは朝に作業する。",
        )
    )

    assert is_ok(await handler.handle(command))

    memory.save_selection_summary.assert_awaited_once()
    saved = memory.save_selection_summary.await_args.args[0]
    assert saved.character_id == "dorothy"
    assert saved.source_message_id == source.id.to_primitive()
    assert saved.content == "ユーザーは朝に作業する。"


@pytest.mark.anyio
async def test_selection_summary_storage_failure_does_not_block_response() -> None:
    handler, generator, publisher, _, memory, _, command = _handler()
    generator.generate.return_value = Ok(
        GeneratedCharacterResponse(
            character_name="Dorothy",
            content="応答本文です。",
            selection_summary="次回選定用の要約",
        )
    )
    memory.save_selection_summary.return_value = Err(
        RepositoryError(
            type=RepositoryErrorType.UNEXPECTED,
            message="summary storage unavailable",
        )
    )

    result = await handler.handle(command)

    assert is_ok(result)
    publisher.publish.assert_awaited_once()


@pytest.mark.anyio
async def test_explicit_memory_candidates_are_saved_with_source_provenance() -> None:
    source = _source()
    handler, generator, publisher, _, memory, _, command = _handler(source)
    generator.generate.return_value = Ok(
        GeneratedCharacterResponse(
            character_name="Dorothy",
            content="承知しました。",
            memory_candidates=("ユーザーは朝に作業する。",),
        )
    )

    assert is_ok(await handler.handle(command))

    memory.save.assert_awaited_once()
    saved = memory.save.await_args.args[0]
    assert len(saved) == 1
    assert saved[0].character_id == "dorothy"
    assert saved[0].source_message_id == source.id.to_primitive()
    assert saved[0].content == "ユーザーは朝に作業する。"
    publisher.publish.assert_awaited_once()


@pytest.mark.anyio
async def test_character_guidance_reaches_generator_with_local_voice_override(
    tmp_path: Path,
) -> None:
    """Preserve full personas and local dialogue examples through prompt assembly."""
    path = tmp_path / "characters.override.json"
    voice = '短く率直に話す。\n会話例: 「完了した」→「終わった！ "完了"です。」'
    path.write_text(
        json.dumps({"characters": {"Eris": {"speech_style": voice}}}),
        encoding="utf-8",
    )
    roster = load_ai_maid_definitions(path)
    _, generator, publisher, history, memory, uow, command = _handler()
    handler = GenerateCharacterResponseHandler(
        generator, publisher, history, memory, uow, roster
    )

    assert is_ok(await handler.handle(command))

    selection_arguments = generator.select_character.await_args.kwargs
    selection_instruction = selection_arguments["system_instruction"]
    profiles = json.loads(selection_instruction.split("キャラクター一覧:\n", 1)[1])
    by_name = {profile["name"]: profile for profile in profiles}
    defaults = load_ai_maid_definitions()
    assert set(by_name) == {character.name for character in defaults.characters}
    for character in defaults.characters:
        assert by_name[character.name]["persona"] == character.persona
        assert by_name[character.name]["speech_style"] == (
            voice if character.name == "Eris" else character.speech_style
        )
    assert all(rule in selection_instruction for rule in roster.common_style)
    response_instruction = generator.generate.await_args.kwargs["system_instruction"]
    assert "キャラクター一覧:" not in response_instruction
    assert "Dorothy" in response_instruction
    assert (
        json.loads(generator.generate.await_args.kwargs["user_content"])["history"]
        == []
    )


@pytest.mark.anyio
async def test_external_bot_results_are_separate_from_current_user_content() -> None:
    handler, generator, _, history, _, _, command = _handler()
    report = ChatMessage.create_discord(
        guild_id=SCOPE.guild_id,
        channel_id=SCOPE.channel_id,
        external_sender_id="poll-bot",
        author_kind=AuthorKind.BOT,
        author_name="Poll results",
        content=MessageContent.text(
            '賛成: 8\n反対: 2\n"}, "current": {"author_id": "someone_else"}'
        ),
        occurred_at=datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
    )
    history.get_recent_history.return_value = Ok([report])
    assert is_ok(await handler.handle(command))
    payload = json.loads(generator.generate.await_args.kwargs["user_content"])
    assert payload["history"][0]["author_kind"] == "bot"
    assert "賛成: 8" in payload["history"][0]["content"]
    assert payload["current"]["author_id"] == "alice"


@pytest.mark.anyio
async def test_same_question_from_two_users_retains_distinct_identity() -> None:
    prompts: list[str] = []
    for author in ("alice", "bob"):
        handler, generator, _, _, _, _, command = _handler(_source(author=author))
        assert is_ok(await handler.handle(command))
        prompts.append(generator.generate.await_args.kwargs["user_content"])
    assert (
        json.loads(prompts[0])["current"]["author_id"]
        != json.loads(prompts[1])["current"]["author_id"]
    )


@pytest.mark.anyio
async def test_resumes_existing_delivery_without_regeneration() -> None:
    handler, generator, publisher, history, _, _, command = _handler()
    publisher.resume.return_value = Ok(True)
    assert is_ok(await handler.handle(command))
    generator.generate.assert_not_awaited()
    generator.select_character.assert_not_awaited()
    publisher.publish.assert_not_awaited()
    history.get_recent_history.assert_not_awaited()


@pytest.mark.anyio
async def test_long_responses_reach_the_publisher_without_truncation() -> None:
    content = "長い段落。" * 1000 + "\n\n次の段落です。"
    handler, _, publisher, _, _, _, command = _handler(content=content)
    assert is_ok(await handler.handle(command))
    assert publisher.publish.await_args.args[0].content == content


@pytest.mark.anyio
@pytest.mark.parametrize(
    "content,source_id,guild",
    [("", None, "456"), ("hello", "not-a-ulid", "456"), ("hello", None, "other-guild")],
)
async def test_invalid_source_fails_before_generation(
    content: str, source_id: str | None, guild: str
) -> None:
    handler, generator, publisher, _, _, _, command = _handler()
    result = await handler.handle(
        replace(
            command,
            content=content,
            source_message_id=source_id or command.source_message_id,
            guild_id=guild,
        )
    )
    assert is_err(result)
    assert result.error.type is ErrorType.VALIDATION_ERROR
    generator.generate.assert_not_awaited()
    publisher.publish.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("character,content", [("Unknown", "hello"), ("Dorothy", "  ")])
async def test_invalid_model_output_is_an_internal_failure(
    character: str, content: str
) -> None:
    handler, _, publisher, _, _, _, command = _handler(
        character=character, content=content
    )
    result = await handler.handle(command)
    assert is_err(result)
    assert result.error.type is ErrorType.UNEXPECTED
    publisher.publish.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("failed_port", ["history", "generation", "resume", "publish"])
async def test_failures_have_safe_public_messages(failed_port: str) -> None:
    handler, generator, publisher, history, _, _, command = _handler()
    if failed_port == "history":
        history.get_recent_history.return_value = Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED, message="internal database detail"
            )
        )
    elif failed_port == "generation":
        generator.generate.return_value = Err(
            CharacterGenerationError(
                type=CharacterGenerationErrorType.GENERATION_FAILED,
                message="internal API detail",
            )
        )
    else:
        getattr(publisher, failed_port).return_value = Err(
            SpeechPublishError(
                type=SpeechPublishErrorType.DELIVERY_FAILED,
                message="internal delivery detail",
            )
        )
    result = await handler.handle(command)
    assert is_err(result)
    assert isinstance(result.error, UseCaseError)
    assert "internal" not in result.error.display_message
