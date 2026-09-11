"""Tests for Times episode generation use case: continuity, bounding, empty output and recovery."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest
from flow_res import Err, Ok, is_ok

from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.messages.times_message import TimesEpisodePlan, TimesPost
from app.contracts.ports.character_response_generator import (
    ICharacterResponseGenerator,
)
from app.contracts.ports.chat_history_query import IChatHistoryQuery
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.contracts.ports.times_publisher import ITimesPublisher
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.characters import (
    AI_MAID_CHARACTERS,
    AI_MAID_COMMON_STYLE,
    CharacterDefinition,
    CharacterRoster,
)
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import (
    DiscordConversationScope,
    MessageContent,
)
from app.usecases.chat.generate_times_episode import (
    GenerateTimesEpisodeCommand,
    GenerateTimesEpisodeHandler,
    _build_times_instruction,
)


def test_times_instruction_preserves_maid_identity_and_board_rules() -> None:
    """Times keeps the maid identities, dialogue style and factual boundaries."""
    instruction = _build_times_instruction(
        CharacterRoster(
            common_style=AI_MAID_COMMON_STYLE,
            characters=AI_MAID_CHARACTERS,
        )
    )

    assert "マスターを「マスター」または「ご主人」と呼ぶ" in instruction
    assert "親密度は高く、忖度せず、必要なら辛辣に指摘する" in instruction
    assert "メイド同士の会話・ツッコミ・意見交換を多めに" in instruction
    assert "単一話者・他のメイドの台詞を代作しない制約は適用しません" in instruction
    assert (
        "事実部分は source_history と current に実際に出た内容だけに限定" in instruction
    )
    assert "「次にこれが来そう」などの推測は可" in instruction
    assert "推測だと分かる表現に" in instruction
    assert "board_memory 内の推測も事実として扱わない" in instruction
    profiles = json.loads(instruction.split("キャラクター一覧:\n", 1)[1])
    assert [(profile["name"], profile["position"]) for profile in profiles] == [
        (character.name, character.position) for character in AI_MAID_CHARACTERS
    ]
    assert ("Dorothy", "メイド長") in [
        (profile["name"], profile["position"]) for profile in profiles
    ]


def _roster() -> CharacterRoster:
    return CharacterRoster(
        characters=(
            CharacterDefinition(
                character_id="dorothy",
                name="Dorothy",
                position="Head Maid",
                responsibilities=("Management",),
                persona="Strict and polite",
                speech_style="Formal",
            ),
            CharacterDefinition(
                character_id="elinor",
                name="Elinor",
                position="Kitchen Maid",
                responsibilities=("Cooking",),
                persona="Warm and cheerful",
                speech_style="Gentle",
            ),
        ),
        common_style=("Always speak gently",),
    )


def _chat_message(
    external_id: str,
    content: str,
    occurred_at: datetime,
    author: str = "alice",
) -> ChatMessage:
    return ChatMessage.create_discord(
        guild_id="456",
        channel_id="123",
        external_sender_id=author,
        author_name=author.title(),
        external_message_id=external_id,
        content=MessageContent.text(content),
        occurred_at=occurred_at,
    )


@pytest.fixture
def times_setup() -> tuple[
    GenerateTimesEpisodeHandler,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    AsyncMock,
    ChatMessage,
]:
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    publisher = AsyncMock(spec=ITimesPublisher)
    times_store = AsyncMock(spec=ITimesEpisodeStore)
    history_query = AsyncMock(spec=IChatHistoryQuery)
    roster = _roster()

    source = _chat_message(
        "100",
        "Hello maids!",
        datetime(2026, 9, 12, 2, 0, tzinfo=UTC),
    )

    history_query.get_by_external_id = AsyncMock(return_value=Ok(source))
    history_query.get_recent_history = AsyncMock(return_value=Ok([]))
    times_store.get = AsyncMock(return_value=Ok(None))
    times_store.save = AsyncMock(return_value=Ok(None))
    times_store.get_recent_completed = AsyncMock(return_value=Ok([]))
    publisher.deliver = AsyncMock(return_value=Ok(None))

    handler = GenerateTimesEpisodeHandler(
        generator=generator,
        publisher=publisher,
        times_store=times_store,
        history_query=history_query,
        roster=roster,
    )
    return handler, generator, publisher, times_store, history_query, source


@pytest.mark.anyio
@pytest.mark.parametrize("master_id", [None, "672491948375932937"])
@pytest.mark.parametrize("has_creation_time", [True, False])
async def test_generate_times_episode_continuity_and_point_in_time_bounding(
    times_setup: tuple[
        GenerateTimesEpisodeHandler,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        ChatMessage,
    ],
    master_id: str | None,
    has_creation_time: bool,
) -> None:
    _, generator, publisher, times_store, history_query, source = times_setup
    handler = GenerateTimesEpisodeHandler(
        generator,
        publisher,
        times_store,
        history_query,
        _roster(),
        DiscordMaster(master_id),
    )

    earlier_msg = _chat_message(
        "99", "Earlier question", datetime(2026, 9, 12, 1, 59, tzinfo=UTC)
    )
    history_query.get_recent_history.return_value = Ok([earlier_msg])

    past_episode = TimesEpisodePlan(
        source_message_id="80",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Dorothy", content="Past discussion note"),),
        status="COMPLETED",
        next_post_index=1,
        created_at=datetime(2026, 9, 11, 15, 30, tzinfo=UTC)
        if has_creation_time
        else None,
    )
    times_store.get_recent_completed.return_value = Ok([past_episode])

    generator.generate_times_episode.return_value = Ok(
        (
            TimesPost(character_name="Dorothy", content="お帰りなさいませ。"),
            TimesPost(character_name="Elinor", content="紅茶を淹れましたよ！"),
        )
    )

    command = GenerateTimesEpisodeCommand(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
    )
    result = await handler.handle(command)

    assert is_ok(result)
    # Check history query was bounded by source occurred_at and internal ID
    history_query.get_recent_history.assert_awaited_once_with(
        DiscordConversationScope(guild_id="456", channel_id="123"),
        limit=20,
        before=(source.occurred_at, source.id.to_primitive()),
    )

    # Board memory is bounded by episode creation order, not source message time.
    times_store.get_recent_completed.assert_awaited_once_with(
        DiscordConversationScope(guild_id="456", channel_id="999"),
        limit=5,
        before=publisher.deliver.call_args.args[0].created_at,
    )
    assert history_query.get_recent_history.await_args.kwargs["before"][0].tzinfo is UTC
    assert times_store.get_recent_completed.await_args.kwargs["before"].tzinfo is UTC

    # Check generated prompt contained explicitly labeled board_memory and source_history
    gen_call = generator.generate_times_episode.call_args.kwargs
    payload = json.loads(gen_call["user_content"])
    assert payload["master"] == (
        {"user_id": master_id, "mention": "<@672491948375932937>"}
        if master_id is not None
        else None
    )
    assert payload["current"]["author_id"] == "alice"
    assert "board_memory" in payload
    assert len(payload["board_memory"]) == 1
    assert payload["board_memory"][0]["source_message_id"] == "80"
    assert payload["board_memory"][0]["created_at"] == (
        "2026-09-12 00:30:00 JST" if has_creation_time else None
    )
    assert payload["board_memory"][0]["posts"][0]["content"] == "Past discussion note"
    assert "source_history" in payload
    assert payload["source_history"][0]["message_id"] == "99"
    assert payload["source_history"][0]["occurred_at"] == "2026-09-12 10:59:00 JST"
    assert payload["current"]["message_id"] == "100"
    assert payload["current"]["occurred_at"] == "2026-09-12 11:00:00 JST"
    assert source.occurred_at.tzinfo is UTC
    if past_episode.created_at is not None:
        assert past_episode.created_at.tzinfo is UTC

    # Check publisher delivered the generated posts
    publisher.deliver.assert_awaited_once()
    delivered_plan: TimesEpisodePlan = publisher.deliver.call_args.args[0]
    assert len(delivered_plan.posts) == 2
    assert delivered_plan.posts[0].character_name == "Dorothy"
    assert delivered_plan.posts[1].character_name == "Elinor"
    assert delivered_plan.status == "DELIVERING"
    assert delivered_plan.created_at is not None
    assert delivered_plan.created_at.tzinfo is UTC


@pytest.mark.anyio
@pytest.mark.parametrize("save_fails", [False, True])
async def test_empty_posts_complete_only_after_the_plan_is_saved(
    times_setup: tuple[
        GenerateTimesEpisodeHandler,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        ChatMessage,
    ],
    save_fails: bool,
) -> None:
    handler, generator, publisher, times_store, _, _ = times_setup

    generator.generate_times_episode.return_value = Ok(())
    if save_fails:
        times_store.save.side_effect = [
            Ok(None),
            Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message="Completion could not be committed.",
                )
            ),
        ]

    command = GenerateTimesEpisodeCommand(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
    )
    result = await handler.handle(command)

    assert is_ok(result) is not save_fails
    # Publisher deliver should NOT be called when posts are empty
    publisher.deliver.assert_not_awaited()
    # Plan saved with COMPLETED status and empty posts
    last_save = times_store.save.call_args_list[-1].args[0]
    assert last_save.status == "COMPLETED"
    assert last_save.posts == ()


@pytest.mark.anyio
async def test_duplicate_completed_episode_returns_early_without_regeneration(
    times_setup: tuple[
        GenerateTimesEpisodeHandler,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        ChatMessage,
    ],
) -> None:
    handler, generator, publisher, times_store, _, _ = times_setup

    already_done = TimesEpisodePlan(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Dorothy", content="Done already"),),
        status="COMPLETED",
        next_post_index=1,
    )
    times_store.get.return_value = Ok(already_done)

    command = GenerateTimesEpisodeCommand(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
    )
    result = await handler.handle(command)

    assert is_ok(result)
    generator.generate_times_episode.assert_not_awaited()
    publisher.deliver.assert_not_awaited()


@pytest.mark.anyio
async def test_already_generated_episode_delivers_without_regeneration(
    times_setup: tuple[
        GenerateTimesEpisodeHandler,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        ChatMessage,
    ],
) -> None:
    handler, generator, publisher, times_store, _, _ = times_setup

    existing_generated = TimesEpisodePlan(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(
            TimesPost(character_name="Dorothy", content="First"),
            TimesPost(character_name="Elinor", content="Second"),
        ),
        status="DELIVERING",
        next_post_index=0,
    )
    times_store.get.return_value = Ok(existing_generated)

    command = GenerateTimesEpisodeCommand(
        source_message_id="100",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
    )
    result = await handler.handle(command)

    assert is_ok(result)
    # Generator was NOT called: no re-generation during delivery recovery!
    generator.generate_times_episode.assert_not_awaited()
    # Publisher was called to deliver existing generated plan
    publisher.deliver.assert_awaited_once_with(existing_generated)


@pytest.mark.anyio
async def test_source_message_must_match_requested_conversation(
    times_setup: tuple[
        GenerateTimesEpisodeHandler,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        AsyncMock,
        ChatMessage,
    ],
) -> None:
    handler, generator, publisher, times_store, _, _ = times_setup

    result = await handler.handle(
        GenerateTimesEpisodeCommand(
            source_message_id="100",
            guild_id="999",
            channel_id="123",
            delivery_channel_id="999",
        )
    )

    assert not is_ok(result)
    generator.generate_times_episode.assert_not_awaited()
    publisher.deliver.assert_not_awaited()
    times_store.get.assert_not_awaited()
