"""Tests for the application mediator composition root."""

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from flow_res import Err, Ok, is_err, is_ok
from injector import Injector
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app import container
from app.application.character_settings import load_ai_maid_definitions
from app.application.mediator import ApplicationMediator, create_application_mediator
from app.contracts.messages import CharacterSelection, GeneratedCharacterResponse
from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.messages.times_message import TimesEpisodePlan, TimesPost
from app.contracts.ports import (
    ICharacterMemoryStore,
    ICharacterResponseGenerator,
    ISpeechPublisher,
    ITimesEpisodeStore,
    ITimesPublisher,
    IUnitOfWork,
)
from app.domain.characters import CharacterRoster
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import AuthorKind, TeamId
from app.infrastructure.discord.times_publisher import DiscordWebhookTimesPublisher
from app.infrastructure.memory.character_memory_store import (
    MarkdownCharacterMemoryStore,
)
from app.infrastructure.queries.times_episode_store import SQLAlchemyTimesEpisodeStore
from app.usecases.chat.generate_character_response import (
    GenerateCharacterResponseCommand,
)
from app.usecases.chat.generate_times_episode import GenerateTimesEpisodeCommand
from app.usecases.chat.save_discord_chat import SaveDiscordChatCommand
from app.usecases.result import ErrorType
from app.usecases.teams.get_team import GetTeamQuery
from app.usecases.users.create_user import CreateUserCommand
from app.usecases.users.get_user import GetUserQuery


@pytest.mark.anyio
async def test_container_provides_dispatching_application_mediator(
    test_db_engine: None,
) -> None:
    """The composition root creates and retrieves a persisted user."""
    injector = Injector([container.configure])
    mediator = injector.get(ApplicationMediator)

    created = await mediator.send_async(
        CreateUserCommand(display_name="Alice", email="alice@example.com")
    )
    assert is_ok(created)
    loaded = await mediator.send_async(GetUserQuery(user_id=created.value.id))
    assert is_ok(loaded)
    assert loaded.value.display_name == "Alice"
    assert loaded.value.email == "alice@example.com"


@pytest.mark.anyio
async def test_mediator_maps_repository_error_at_application_boundary() -> None:
    """Repository errors are classified when they leave the application layer."""
    repository = MagicMock()
    repository.get_by_id = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.VERSION_CONFLICT,
                message="stale database version",
            )
        )
    )
    uow = MagicMock(spec=IUnitOfWork)
    uow.GetRepository.return_value = repository
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)

    injector = Injector()
    injector.binder.bind(IUnitOfWork, to=uow)
    mediator = create_application_mediator(injector)

    result = await mediator.send_async(
        GetTeamQuery(id=TeamId.generate().expect("valid team id").to_primitive())
    )

    assert is_err(result)
    assert result.error.type is ErrorType.CONCURRENCY_CONFLICT
    assert result.error.message == "stale database version"
    assert result.error.display_message != "stale database version"


@pytest.mark.anyio
async def test_mediator_connects_saved_bot_context_and_human_response(
    test_db_engine: None,
) -> None:
    """Exercise real DI, source persistence and scoped history with mocked external IO."""
    injector = Injector([container.configure])
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    generator.select_character.return_value = Ok(CharacterSelection("Dorothy"))
    generator.generate.return_value = Ok(
        GeneratedCharacterResponse("Dorothy", "賛成が8票です。")
    )
    publisher = AsyncMock(spec=ISpeechPublisher)
    publisher.resume.return_value = Ok(False)
    publisher.publish.return_value = Ok(None)
    memory = AsyncMock(spec=ICharacterMemoryStore)
    memory.get_selection_summaries.return_value = Ok({})
    memory.get_relevant.return_value = Ok([])
    memory.save.return_value = Ok(None)
    memory.save_selection_summary.return_value = Ok(None)
    injector.binder.bind(ICharacterResponseGenerator, to=generator)
    injector.binder.bind(ISpeechPublisher, to=publisher)
    injector.binder.bind(ICharacterMemoryStore, to=memory)
    injector.binder.bind(CharacterRoster, to=load_ai_maid_definitions())
    injector.binder.bind(DiscordMaster, to=DiscordMaster("672491948375932937"))
    mediator = injector.get(ApplicationMediator)
    start = datetime(2026, 9, 12, tzinfo=UTC)
    assert is_ok(
        await mediator.send_async(
            SaveDiscordChatCommand(
                external_sender_id="999",
                guild_id="456",
                channel_id="123",
                content="賛成8票、反対2票",
                occurred_at=start,
                author_kind=AuthorKind.BOT,
                external_message_id="99",
                author_name="Poll Bot",
            )
        )
    )
    source = await mediator.send_async(
        SaveDiscordChatCommand(
            external_sender_id="2",
            guild_id="456",
            channel_id="123",
            content="結果を教えて",
            occurred_at=start + timedelta(seconds=1),
            external_message_id="100",
            author_name="Alice",
        )
    )
    assert is_ok(source)
    result = await mediator.send_async(
        GenerateCharacterResponseCommand(
            content="結果を教えて",
            guild_id="456",
            channel_id="123",
            source_message_id=source.value.id,
            delivery_channel_id="123",
        )
    )
    assert is_ok(result)
    assert generator.generate.await_args is not None
    prompt = json.loads(generator.generate.await_args.kwargs["user_content"])
    assert prompt["master"] == {
        "user_id": "672491948375932937",
        "mention": "<@672491948375932937>",
    }
    assert prompt["current"]["author_name"] == "Alice"
    assert prompt["current"]["is_master"] is False
    assert prompt["history"][0]["author_name"] == "Poll Bot"
    assert prompt["history"][0]["author_kind"] == "bot"
    publisher.publish.assert_awaited_once()
    assert publisher.publish.await_args is not None
    assert publisher.publish.await_args.args[0].source_message_id == "100"


@pytest.mark.anyio
async def test_mediator_delivers_times_to_a_separate_board_without_regeneration(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Connect source persistence, pending plans and delivery with external IO mocked."""
    injector = Injector([container.configure])
    roster = load_ai_maid_definitions()
    master = DiscordMaster("672491948375932937")
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    generator.generate_times_episode.return_value = Ok(
        (
            TimesPost(
                character_name="Dorothy",
                content="今日の記録です。",
                memory_candidates=("Timesで今日の記録を話した。",),
                selection_summary="今日の記録について話した。",
            ),
        )
    )
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    memory_store = MarkdownCharacterMemoryStore(tmp_path)
    webhook = MagicMock(spec=discord.Webhook)
    webhook.id, webhook.guild_id, webhook.channel_id = 9999, 456, 999
    webhook.fetch = AsyncMock(return_value=webhook)
    webhook.send = AsyncMock(return_value=MagicMock(spec=discord.WebhookMessage))
    webhook.send.return_value.created_at = datetime(2026, 9, 12, 1, tzinfo=UTC)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id, channel.guild.id = 999, 456
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(discord.Webhook, "from_url", MagicMock(return_value=webhook))
    publisher = DiscordWebhookTimesPublisher(
        "https://discord.com/api/webhooks/123456789012345678/" + "a" * 68,
        client=client,
        store=store,
        memory_store=memory_store,
        roster=roster,
        master=master,
    )
    await publisher.initialize("456", character_channel_ids={"123"})
    injector.binder.bind(CharacterRoster, to=roster)
    injector.binder.bind(DiscordMaster, to=master)
    injector.binder.bind(ICharacterResponseGenerator, to=generator)
    injector.binder.bind(ITimesEpisodeStore, to=store)
    injector.binder.bind(ICharacterMemoryStore, to=memory_store)
    injector.binder.bind(ITimesPublisher, to=publisher)
    mediator = injector.get(ApplicationMediator)
    source = await mediator.send_async(
        SaveDiscordChatCommand(
            external_sender_id="2",
            guild_id="456",
            channel_id="123",
            content="今日の記録を残して",
            occurred_at=datetime(2026, 9, 12, tzinfo=UTC),
            external_message_id="100",
        )
    )
    assert is_ok(source)
    assert is_ok(
        await store.save(
            TimesEpisodePlan(
                source_message_id="100",
                guild_id="456",
                channel_id="123",
                delivery_channel_id="999",
            )
        )
    )
    command = GenerateTimesEpisodeCommand(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
    )

    assert is_ok(await mediator.send_async(command))
    restarted_store = SQLAlchemyTimesEpisodeStore(session_factory)
    persisted = await restarted_store.get("100")
    assert is_ok(persisted) and persisted.value is not None
    assert persisted.value.channel_id == "123"
    assert persisted.value.delivery_channel_id == "999"
    assert persisted.value.status == "COMPLETED"
    memories = (await memory_store.get_relevant(character_id="dorothy")).unwrap()
    assert [memory.content for memory in memories] == ["Timesで今日の記録を話した。"]
    assert memories[0].source_message_id == "times:100:00"
    summaries = (
        await memory_store.get_selection_summaries(character_ids=("dorothy",))
    ).unwrap()
    assert summaries["dorothy"].content == "今日の記録について話した。"
    injector.binder.bind(ITimesEpisodeStore, to=restarted_store)
    assert is_ok(await mediator.send_async(command))
    assert is_err(
        await mediator.send_async(replace(command, source_message_id=source.value.id))
    )
    generator.generate_times_episode.assert_awaited_once()
    assert generator.generate_times_episode.await_args is not None
    prompt = json.loads(
        generator.generate_times_episode.await_args.kwargs["user_content"]
    )
    assert prompt["master"] == {
        "user_id": "672491948375932937",
        "mention": "<@672491948375932937>",
    }
    webhook.send.assert_awaited_once()
    assert webhook.send.await_args is not None
    assert webhook.send.await_args.kwargs["content"] == "今日の記録です。"
    assert webhook.send.await_args.kwargs["allowed_mentions"].to_dict() == {
        "parse": [],
        "users": [672491948375932937],
    }
