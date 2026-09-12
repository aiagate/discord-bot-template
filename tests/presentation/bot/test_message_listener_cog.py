"""Routing, bot context and bounded FIFO behavior of the Discord listener."""

import asyncio
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from discord.ext import commands
from flow_res import Ok

from app.domain.value_objects import AuthorKind, DiscordConversationScope
from app.presentation.bot.cogs import message_listener_cog
from app.usecases.chat.generate_character_response import (
    GenerateCharacterResponseCommand,
)
from app.usecases.chat.save_discord_chat import SaveChatResult, SaveDiscordChatCommand

SCOPE = DiscordConversationScope(guild_id="456", channel_id="123")


def _message(
    message_id: int = 100,
    *,
    content: str = "hello",
    channel_id: int = 123,
    parent_id: int | None = None,
    guild_id: int | None = 456,
    bot: bool = False,
    webhook_id: int | None = None,
) -> MagicMock:
    message = MagicMock(spec=discord.Message)
    message.id = message_id
    message.author = SimpleNamespace(
        id=2, bot=bot, display_name="Poll Bot" if bot else "Alice"
    )
    channel_type = (
        discord.Thread
        if parent_id is not None
        else discord.TextChannel
        if guild_id is not None
        else discord.DMChannel
    )
    message.channel = MagicMock(spec=channel_type)
    message.channel.id = channel_id
    if parent_id is not None:
        message.channel.parent_id = parent_id
    message.guild = SimpleNamespace(id=guild_id) if guild_id is not None else None
    message.content = content
    message.created_at = datetime(2026, 9, 12, 1, 0, tzinfo=UTC)
    message.webhook_id = webhook_id
    message.reference = None
    message.embeds = []
    message.reply = AsyncMock()
    return message


def _cog(
    *,
    enabled: bool = True,
    forum: bool = False,
    destinations: tuple[message_listener_cog.DiscordResponseDestination, ...]
    | None = None,
) -> tuple[message_listener_cog.DiscordMessageListenerCog, AsyncMock, MagicMock]:
    bot = MagicMock(spec=commands.Bot)
    bot.user = SimpleNamespace(id=1, mention="<@1>")
    bot.get_context = AsyncMock(return_value=SimpleNamespace(prefix=None))

    async def send(command: object) -> object:
        if isinstance(command, SaveDiscordChatCommand):
            return Ok(SaveChatResult(id=str(command.external_message_id)))
        assert isinstance(command, GenerateCharacterResponseCommand)
        return Ok(None)

    send_async = AsyncMock(side_effect=send)
    mediator = MagicMock()
    mediator.send_async = send_async
    if destinations is None:
        destinations = (
            (message_listener_cog.DiscordResponseDestination(SCOPE, 999, forum),)
            if enabled
            else ()
        )
    return (
        message_listener_cog.DiscordMessageListenerCog(
            bot,
            mediator,
            ai_response_destinations=destinations,
        ),
        send_async,
        bot,
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "guild_id,channel_id,enabled",
    [(456, 124, True), (457, 123, True), (456, 123, False)],
)
async def test_other_guild_scopes_and_disabled_ai_only_persist(
    guild_id: int, channel_id: int, enabled: bool
) -> None:
    cog, send, _ = _cog(enabled=enabled)
    message = _message(guild_id=guild_id, channel_id=channel_id)
    await cog.on_message(message)
    send.assert_awaited_once()
    assert send.await_args is not None
    command = send.await_args.args[0]
    assert isinstance(command, SaveDiscordChatCommand)
    assert command.occurred_at is message.created_at
    assert command.external_message_id == str(message.id)
    assert command.guild_id == str(guild_id)
    assert cog._queue.empty()


@pytest.mark.anyio
async def test_direct_messages_are_ignored_without_persistence() -> None:
    cog, send, _ = _cog()

    await cog.on_message(_message(guild_id=None))

    send.assert_not_awaited()
    assert cog._queue.empty()


@pytest.mark.anyio
@pytest.mark.parametrize("webhook_id", [None, 777])
async def test_other_bots_and_webhooks_are_saved_as_context(
    webhook_id: int | None,
) -> None:
    cog, send, bot = _cog()
    message = _message(content="", bot=True, webhook_id=webhook_id)
    embed = discord.Embed(title="アンケート結果", description="参加者10人")
    embed.add_field(name="賛成", value="8")
    embed.add_field(name="反対", value="2")
    message.embeds = [embed]
    await cog.on_message(message)
    assert send.await_args is not None
    command = send.await_args.args[0]
    assert command.author_kind is AuthorKind.BOT
    assert command.author_name == "Poll Bot"
    assert "賛成: 8" in command.content
    assert "反対: 2" in command.content
    assert cog._queue.empty()
    bot.get_context.assert_not_awaited()


@pytest.mark.anyio
async def test_own_bot_and_webhook_do_not_create_response_loops() -> None:
    cog, send, bot = _cog()
    own = _message()
    own.author = bot.user
    await cog.on_message(own)
    await cog.on_message(_message(webhook_id=999, bot=True))
    send.assert_not_awaited()


@pytest.mark.anyio
async def test_work_webhooks_are_ignored_without_character_chat() -> None:
    _, send, bot = _cog(enabled=False)
    handler = AsyncMock(return_value=True)
    cog = message_listener_cog.DiscordMessageListenerCog(
        bot,
        MagicMock(send_async=send),
        work_handler=handler,
        ignored_webhook_ids=(777,),
    )
    await cog.on_message(_message(webhook_id=777, bot=True, content="成果報告"))
    send.assert_not_awaited()
    handler.assert_not_awaited()
    assert cog._queue.empty()


@pytest.mark.anyio
async def test_prefix_commands_are_saved_without_character_response() -> None:
    cog, send, bot = _cog()
    bot.get_context.return_value = SimpleNamespace(prefix="!")
    await cog.on_message(_message(content="!help"))
    send.assert_awaited_once()
    assert cog._queue.empty()


@pytest.mark.anyio
@pytest.mark.parametrize("content", ["hello", "<@1> hello", "<@!1> hello"])
async def test_messages_are_answered_without_requiring_a_mention(content: str) -> None:
    cog, send, _ = _cog()
    await cog.cog_load()
    try:
        await cog.on_message(_message(content=content))
        await cog._queue.join()
    finally:
        await cog.cog_unload()
    assert send.await_count == 2
    command = send.await_args_list[1].args[0]
    assert isinstance(command, GenerateCharacterResponseCommand)
    assert command.content == "hello"
    assert command.source_message_id == "100"


@pytest.mark.anyio
async def test_forum_threads_use_thread_scope_and_parent_for_delivery() -> None:
    cog, send, _ = _cog(forum=True)
    message = _message(channel_id=789, parent_id=123)
    await cog.cog_load()
    try:
        await cog.on_message(message)
        await cog._queue.join()
    finally:
        await cog.cog_unload()

    command = send.await_args_list[1].args[0]
    assert isinstance(command, GenerateCharacterResponseCommand)
    assert command.channel_id == "789"
    assert command.delivery_channel_id == "123"


@pytest.mark.anyio
async def test_multiple_destinations_route_text_and_forum_messages() -> None:
    forum_scope = DiscordConversationScope(guild_id="456", channel_id="321")
    cog, send, _ = _cog(
        destinations=(
            message_listener_cog.DiscordResponseDestination(SCOPE, 999, False),
            message_listener_cog.DiscordResponseDestination(forum_scope, 998, True),
        )
    )
    await cog.cog_load()
    try:
        await cog.on_message(_message(channel_id=123))
        await cog.on_message(_message(channel_id=789, parent_id=321))
        await cog._queue.join()
    finally:
        await cog.cog_unload()

    response_commands = [
        call.args[0]
        for call in send.await_args_list
        if isinstance(call.args[0], GenerateCharacterResponseCommand)
    ]
    assert [command.delivery_channel_id for command in response_commands] == [
        "123",
        "321",
    ]


@pytest.mark.anyio
async def test_forum_threads_from_another_parent_are_saved_only() -> None:
    cog, send, _ = _cog(forum=True)
    await cog.on_message(_message(channel_id=789, parent_id=124))

    assert send.await_count == 1
    assert cog._queue.empty()


@pytest.mark.anyio
async def test_second_response_waits_for_first_to_finish() -> None:
    cog, send, _ = _cog()
    started, release = asyncio.Event(), asyncio.Event()
    completed: list[str] = []

    async def handle(command: object) -> object:
        if isinstance(command, SaveDiscordChatCommand):
            return Ok(SaveChatResult(id=str(command.external_message_id)))
        assert isinstance(command, GenerateCharacterResponseCommand)
        if command.source_message_id == "100":
            started.set()
            await release.wait()
        completed.append(command.source_message_id)
        return Ok(None)

    send.side_effect = handle
    await cog.cog_load()
    try:
        await cog.on_message(_message(100))
        await started.wait()
        await cog.on_message(_message(101))
        await asyncio.sleep(0)
        assert completed == []
        assert cog._queue.qsize() == 1
        release.set()
        await cog._queue.join()
        assert completed == ["100", "101"]
    finally:
        await cog.cog_unload()


@pytest.mark.anyio
async def test_slow_save_does_not_reverse_receive_order() -> None:
    cog, send, _ = _cog()
    saving, release = asyncio.Event(), asyncio.Event()

    async def save(command: SaveDiscordChatCommand) -> object:
        if command.external_message_id == "100":
            saving.set()
            await release.wait()
        return Ok(SaveChatResult(id=str(command.external_message_id)))

    send.side_effect = save
    first = asyncio.create_task(cog.on_message(_message(100)))
    await saving.wait()
    second = asyncio.create_task(cog.on_message(_message(101)))
    await asyncio.sleep(0)
    release.set()
    await asyncio.gather(first, second)
    assert cog._queue.get_nowait().command.source_message_id == "100"
    assert cog._queue.get_nowait().command.source_message_id == "101"


@pytest.mark.anyio
async def test_queue_overload_is_bounded_and_all_messages_are_saved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_listener_cog, "MAX_PENDING_RESPONSES", 2)
    cog, send, _ = _cog()
    messages = [_message(index) for index in range(10)]
    for message in messages:
        await cog.on_message(message)
    assert cog._queue.qsize() == 2
    assert send.await_count == 10
    assert sum(message.reply.await_count for message in messages) == 1


@pytest.mark.anyio
async def test_expired_work_does_not_call_the_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_listener_cog, "MAX_QUEUE_WAIT_SECONDS", 0.0)
    cog, send, _ = _cog()
    message = _message()
    await cog.on_message(message)
    await cog.cog_load()
    try:
        await cog._queue.join()
    finally:
        await cog.cog_unload()
    send.assert_awaited_once()
    message.reply.assert_awaited_once()
    assert message.reply.await_args.kwargs["allowed_mentions"].everyone is False


@pytest.mark.anyio
async def test_processing_timeout_releases_consumer_for_next_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(message_listener_cog, "RESPONSE_TIMEOUT_SECONDS", 0.01)
    cog, send, _ = _cog()

    async def handle(command: object) -> object:
        if isinstance(command, SaveDiscordChatCommand):
            return Ok(SaveChatResult(id=str(command.external_message_id)))
        assert isinstance(command, GenerateCharacterResponseCommand)
        if command.source_message_id == "100":
            await asyncio.Event().wait()
        return Ok(None)

    send.side_effect = handle
    first, second = _message(100), _message(101)
    await cog.on_message(first)
    await cog.on_message(second)
    await cog.cog_load()
    try:
        await cog._queue.join()
    finally:
        await cog.cog_unload()
    first.reply.assert_awaited_once()
    second.reply.assert_not_awaited()
    assert send.await_count == 4
