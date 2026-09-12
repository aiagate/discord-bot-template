"""Tests for Discord Times trigger filtering, loop prevention, and independent consumer."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands
from flow_res import Err, Ok

from app.contracts.messages.times_message import TimesEpisodePlan
from app.contracts.ports.chat_history_query import IChatHistoryQuery
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.value_objects import (
    AuthorKind,
    DiscordConversationScope,
    MessageContent,
)
from app.presentation.bot.cogs import message_listener_cog
from app.presentation.bot.cogs.message_listener_cog import (
    DiscordMessageListenerCog,
    DiscordResponseDestination,
    DiscordTimesDestination,
)
from app.usecases.chat.generate_character_response import (
    GenerateCharacterResponseCommand,
)
from app.usecases.chat.generate_times_episode import (
    GenerateTimesEpisodeCommand,
)
from app.usecases.chat.save_discord_chat import SaveChatResult, SaveDiscordChatCommand
from app.usecases.result import ErrorType, UseCaseError

CHAR_SCOPE = DiscordConversationScope(guild_id="456", channel_id="123")
TIMES_SCOPE = DiscordConversationScope(guild_id="456", channel_id="789")


def _message(
    message_id: int = 100,
    *,
    content: str = "Hello everyone",
    channel_id: int = 123,
    guild_id: int | None = 456,
    bot: bool = False,
    webhook_id: int | None = None,
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.id = message_id
    message.author = SimpleNamespace(
        id=2, bot=bot, display_name="Bot" if bot else "Alice"
    )
    message.channel = MagicMock(spec=discord.TextChannel)
    message.channel.id = channel_id
    message.guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    message.content = content
    message.created_at = datetime(2026, 9, 12, 1, 0, tzinfo=UTC)
    message.webhook_id = webhook_id
    message.reference = None
    message.embeds = []
    message.reply = AsyncMock()
    return message


@pytest.fixture
def listener_setup() -> tuple[
    DiscordMessageListenerCog,
    AsyncMock,
    AsyncMock,
    MagicMock,
]:
    bot = MagicMock(spec=commands.Bot)
    bot.user = SimpleNamespace(id=1, mention="<@1>")
    bot.get_context = AsyncMock(return_value=SimpleNamespace(prefix=None))

    mediator = MagicMock()
    dispatched_commands: list[object] = []

    async def send(cmd: object) -> object:
        dispatched_commands.append(cmd)
        if isinstance(cmd, SaveDiscordChatCommand):
            return Ok(SaveChatResult(id=str(cmd.external_message_id)))
        return Ok(None)

    send_async = AsyncMock(side_effect=send)
    mediator.send_async = send_async

    times_store = AsyncMock(spec=ITimesEpisodeStore)
    times_store.save = AsyncMock(return_value=Ok(None))
    times_store.get = AsyncMock(return_value=Ok(None))
    times_store.pending = AsyncMock(return_value=Ok([]))

    char_destination = DiscordResponseDestination(
        CHAR_SCOPE, webhook_id=999, is_forum=False
    )
    times_destination = DiscordTimesDestination(TIMES_SCOPE, webhook_id=888)

    cog = DiscordMessageListenerCog(
        bot,
        mediator,
        ai_response_destinations=(char_destination,),
        times_destination=times_destination,
        times_store=times_store,
    )
    return cog, send_async, times_store.save, bot


@pytest.mark.anyio
async def test_user_message_in_character_destination_triggers_both_character_and_times(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, send_async, times_store_save, _ = listener_setup
    msg = _message(100, channel_id=123, content="Good morning")

    await cog.on_message(msg)

    # Save command is sent immediately
    assert isinstance(send_async.call_args_list[0].args[0], SaveDiscordChatCommand)

    # Times pending plan was durably saved
    times_store_save.assert_awaited_once()
    plan_arg: TimesEpisodePlan = times_store_save.call_args.args[0]
    assert plan_arg.source_message_id == "100"
    assert plan_arg.guild_id == "456"
    assert plan_arg.channel_id == "123"
    assert plan_arg.delivery_channel_id == "789"
    assert plan_arg.status == "PENDING"

    # Queues: character response queue has 1 item, times queue has 1 item
    assert cog._queue.qsize() == 1
    char_item = cog._queue.get_nowait()
    assert char_item.command.content == "Good morning"
    assert char_item.command.source_message_id == "100"

    assert cog._times_queue.qsize() == 1
    times_cmd = cog._times_queue.get_nowait()
    assert times_cmd.source_message_id == "100"
    assert times_cmd.channel_id == "123"
    assert times_cmd.delivery_channel_id == "789"


@pytest.mark.anyio
async def test_user_message_outside_character_destination_triggers_times_only(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, send_async, times_store_save, _ = listener_setup
    msg = _message(150, channel_id=456, content="I found a new project idea")

    await cog.on_message(msg)

    assert cog._queue.qsize() == 0
    assert cog._times_queue.qsize() == 1
    assert isinstance(send_async.call_args.args[0], SaveDiscordChatCommand)
    times_store_save.assert_awaited_once()
    times_command = cog._times_queue.get_nowait()
    assert times_command == GenerateTimesEpisodeCommand(
        source_message_id="150",
        guild_id="456",
        channel_id="456",
        delivery_channel_id="789",
    )


@pytest.mark.anyio
async def test_user_message_from_another_guild_does_not_trigger_times(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, _, times_store_save, _ = listener_setup
    msg = _message(160, channel_id=456, guild_id=999, content="Other guild")

    await cog.on_message(msg)

    times_store_save.assert_not_awaited()
    assert cog._times_queue.qsize() == 0


@pytest.mark.anyio
async def test_times_webhook_message_is_ignored_preventing_loops(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, send_async, times_store_save, _ = listener_setup
    # Message sent by the Times webhook itself (webhook_id=888)
    msg = _message(200, channel_id=789, content="Times post", webhook_id=888)

    await cog.on_message(msg)

    # Should be completely ignored (not even saved)
    send_async.assert_not_awaited()
    times_store_save.assert_not_awaited()
    assert cog._queue.qsize() == 0
    assert cog._times_queue.qsize() == 0


@pytest.mark.anyio
async def test_character_webhook_message_is_ignored_preventing_loops(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, send_async, times_store_save, _ = listener_setup
    # Message sent by the Character webhook (webhook_id=999)
    msg = _message(300, channel_id=123, content="Character post", webhook_id=999)

    await cog.on_message(msg)

    # Should be completely ignored
    send_async.assert_not_awaited()
    times_store_save.assert_not_awaited()
    assert cog._queue.qsize() == 0
    assert cog._times_queue.qsize() == 0


@pytest.mark.anyio
async def test_external_webhook_triggers_character_response_but_not_times(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, send_async, times_store_save, bot = listener_setup
    msg = _message(400, channel_id=123, content="External alert", webhook_id=777)

    await cog.on_message(msg)

    save_command = send_async.call_args_list[0].args[0]
    assert isinstance(save_command, SaveDiscordChatCommand)
    assert save_command.author_kind is AuthorKind.WEBHOOK
    assert save_command.external_sender_id == "777"
    assert cog._queue.qsize() == 1
    assert cog._times_queue.qsize() == 0
    times_store_save.assert_not_awaited()
    bot.get_context.assert_not_awaited()


@pytest.mark.anyio
async def test_independent_consumers_times_failure_does_not_block_character_responses(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, _, _, _ = listener_setup

    char_executed = asyncio.Event()
    times_executed = asyncio.Event()

    async def mock_send(cmd: object) -> object:
        if isinstance(cmd, GenerateCharacterResponseCommand):
            char_executed.set()
            return Ok(None)
        if isinstance(cmd, GenerateTimesEpisodeCommand):
            times_executed.set()
            raise RuntimeError("Times model service down")
        return Ok(None)

    cog.mediator.send_async = AsyncMock(side_effect=mock_send)

    await cog.cog_load()
    try:
        # Enqueue both
        msg = _message(500, channel_id=123, content="Test independence")
        cog._queue.put_nowait(
            message_listener_cog._QueuedResponse(
                command=GenerateCharacterResponseCommand(
                    content="Test independence",
                    guild_id="456",
                    channel_id="123",
                    source_message_id="500",
                    delivery_channel_id="123",
                ),
                message=msg,
                expires_at=asyncio.get_running_loop().time() + 60,
            )
        )
        cog._times_queue.put_nowait(
            GenerateTimesEpisodeCommand(
                source_message_id="500",
                guild_id="456",
                channel_id="123",
                delivery_channel_id="789",
            )
        )

        # Both workers should run independently
        await asyncio.wait_for(char_executed.wait(), timeout=5.0)
        await asyncio.wait_for(times_executed.wait(), timeout=5.0)
        assert char_executed.is_set()
        assert times_executed.is_set()
    finally:
        await cog.cog_unload()


@pytest.mark.anyio
async def test_times_generation_failure_terminates_unfinished_plan(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, _, _, _ = listener_setup
    times_store = cast(AsyncMock, cog._times_store)
    assert times_store is not None
    plan = TimesEpisodePlan(
        source_message_id="501",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="789",
        status="PENDING",
    )
    times_store.get.return_value = Ok(plan)
    cog.mediator.send_async = AsyncMock(
        return_value=Err(
            UseCaseError(type=ErrorType.UNEXPECTED, message="model unavailable")
        )
    )

    await cog.cog_load()
    try:
        cog._times_queue.put_nowait(
            GenerateTimesEpisodeCommand(
                source_message_id="501",
                guild_id="456",
                channel_id="123",
                delivery_channel_id="789",
            )
        )
        await asyncio.wait_for(cog._times_queue.join(), timeout=1.0)
    finally:
        await cog.cog_unload()

    failed_plan: TimesEpisodePlan = times_store.save.call_args.args[0]
    assert failed_plan.status == "FAILED"
    assert failed_plan.failure == "model unavailable"


@pytest.mark.anyio
async def test_recover_times_queue_requeues_durable_episodes(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, _, _, _ = listener_setup
    plan = TimesEpisodePlan(
        source_message_id="501",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="789",
        status="PENDING",
    )
    times_store = cast(AsyncMock, cog._times_store)
    assert times_store is not None
    times_store.pending = AsyncMock(return_value=Ok([plan]))

    await cog._recover_times_queue()

    times_store.pending.assert_awaited_once_with(
        DiscordConversationScope(guild_id="456", channel_id="789")
    )
    assert cog._times_queue.qsize() == 1
    command = cog._times_queue.get_nowait()
    assert command == GenerateTimesEpisodeCommand(
        source_message_id="501",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="789",
    )
    cog._times_queue.task_done()


@pytest.mark.anyio
async def test_recover_times_queue_restores_heartbeat_source_context(
    listener_setup: tuple[
        DiscordMessageListenerCog,
        AsyncMock,
        AsyncMock,
        MagicMock,
    ],
) -> None:
    cog, _, _, _ = listener_setup
    plan = TimesEpisodePlan(
        source_message_id="heartbeat:789:501",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="789",
        context_message_id="501",
        status="PENDING",
    )
    times_store = cast(AsyncMock, cog._times_store)
    assert times_store is not None
    times_store.pending = AsyncMock(return_value=Ok([plan]))

    await cog._recover_times_queue()

    command = cog._times_queue.get_nowait()
    assert command == GenerateTimesEpisodeCommand(
        source_message_id="501",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="789",
        episode_id="heartbeat:789:501",
    )
    cog._times_queue.task_done()


def _heartbeat_source(occurred_at: datetime) -> ChatMessage:
    return ChatMessage.create_discord(
        guild_id="456",
        channel_id="123",
        external_sender_id="2",
        external_message_id="501",
        author_name="Alice",
        content=MessageContent.text("A topic worth revisiting"),
        occurred_at=occurred_at,
    )


@pytest.mark.anyio
async def test_times_heartbeat_queues_one_delayed_follow_up() -> None:
    bot = MagicMock(spec=commands.Bot)
    mediator = MagicMock()
    store = AsyncMock(spec=ITimesEpisodeStore)
    history_query = AsyncMock(spec=IChatHistoryQuery)
    store.pending.return_value = Ok([])
    history_query.get_recent_discord_user_messages.return_value = Ok(
        [_heartbeat_source(datetime(2026, 9, 12, 1, 0, tzinfo=UTC))]
    )
    store.get.return_value = Ok(None)
    store.save.return_value = Ok(None)
    cog = DiscordMessageListenerCog(
        bot,
        mediator,
        times_destination=DiscordTimesDestination(TIMES_SCOPE, webhook_id=888),
        times_store=store,
        history_query=history_query,
    )

    await cog._run_times_heartbeat(
        now=datetime(2026, 9, 12, 1, 20, tzinfo=UTC),
    )

    saved_plan: TimesEpisodePlan = store.save.call_args.args[0]
    assert saved_plan.source_message_id == "heartbeat:789:501"
    assert saved_plan.context_message_id == "501"
    command = cog._times_queue.get_nowait()
    assert command == GenerateTimesEpisodeCommand(
        source_message_id="501",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="789",
        episode_id="heartbeat:789:501",
    )
    cog._times_queue.task_done()


@pytest.mark.anyio
async def test_times_heartbeat_waits_until_topic_is_twenty_minutes_old() -> None:
    bot = MagicMock(spec=commands.Bot)
    mediator = MagicMock()
    store = AsyncMock(spec=ITimesEpisodeStore)
    history_query = AsyncMock(spec=IChatHistoryQuery)
    store.pending.return_value = Ok([])
    history_query.get_recent_discord_user_messages.return_value = Ok(
        [_heartbeat_source(datetime(2026, 9, 12, 1, 0, tzinfo=UTC))]
    )
    cog = DiscordMessageListenerCog(
        bot,
        mediator,
        times_destination=DiscordTimesDestination(TIMES_SCOPE, webhook_id=888),
        times_store=store,
        history_query=history_query,
    )

    await cog._run_times_heartbeat(
        now=datetime(2026, 9, 12, 1, 19, tzinfo=UTC),
    )

    store.save.assert_not_awaited()
    assert cog._times_queue.empty()


@pytest.mark.anyio
async def test_times_heartbeat_skips_a_topic_older_than_thirty_minutes() -> None:
    bot = MagicMock(spec=commands.Bot)
    mediator = MagicMock()
    store = AsyncMock(spec=ITimesEpisodeStore)
    history_query = AsyncMock(spec=IChatHistoryQuery)
    store.pending.return_value = Ok([])
    history_query.get_recent_discord_user_messages.return_value = Ok(
        [_heartbeat_source(datetime(2026, 9, 12, 1, 0, tzinfo=UTC))]
    )
    cog = DiscordMessageListenerCog(
        bot,
        mediator,
        times_destination=DiscordTimesDestination(TIMES_SCOPE, webhook_id=888),
        times_store=store,
        history_query=history_query,
    )

    await cog._run_times_heartbeat(
        now=datetime(2026, 9, 12, 1, 31, tzinfo=UTC),
    )

    store.save.assert_not_awaited()
    assert cog._times_queue.empty()
