"""Tests for the Discord ChatMessage save use case."""

from datetime import UTC, datetime

import pytest
from flow_res import is_err, is_ok

from app.contracts.ports import IChatHistoryQuery, IUnitOfWork
from app.domain.value_objects import AuthorKind, ChatPlatform, DiscordConversationScope
from app.usecases.chat.save_discord_chat import (
    SaveDiscordChatCommand,
    SaveDiscordChatHandler,
)


@pytest.mark.anyio
async def test_save_chat_persists_discord_message(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """Incoming Discord messages retain external sender and scope."""
    handler = SaveDiscordChatHandler(uow, chat_history_query)

    result = await handler.handle(
        SaveDiscordChatCommand(
            external_sender_id="discord-user-1",
            guild_id="guild-1",
            channel_id="channel-1",
            content="hello",
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        )
    )

    assert not is_err(result)
    assert result.value.id
    history_result = await chat_history_query.get_recent_history(
        DiscordConversationScope(guild_id="guild-1", channel_id="channel-1"),
        limit=10,
    )

    assert not is_err(history_result)
    assert len(history_result.value) == 1
    message = history_result.value[0]
    assert message.external_sender_id.to_primitive() == "discord-user-1"
    assert message.content.payload["text"] == "hello"
    assert message.occurred_at == datetime(2026, 9, 5, 9, 0, tzinfo=UTC)


@pytest.mark.anyio
async def test_duplicate_discord_event_preserves_one_message_and_bot_identity(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    handler = SaveDiscordChatHandler(uow, chat_history_query)
    command = SaveDiscordChatCommand(
        external_sender_id="999",
        guild_id="456",
        channel_id="123",
        content="アンケート結果: 賛成8",
        occurred_at=datetime(2026, 9, 12, tzinfo=UTC),
        author_kind=AuthorKind.BOT,
        external_message_id="100",
        author_name="Poll Bot",
        reply_to_external_message_id="99",
    )
    first = await handler.handle(command)
    second = await handler.handle(command)
    assert is_ok(first) and is_ok(second) and first.value.id == second.value.id
    history = await chat_history_query.get_recent_history(
        DiscordConversationScope(guild_id="456", channel_id="123")
    )
    assert is_ok(history) and len(history.value) == 1
    message = history.value[0]
    assert message.external_message_id == "100"
    assert message.author_name == "Poll Bot"
    assert message.author_kind is AuthorKind.BOT
    assert message.reply_to_external_message_id == "99"
    found = await chat_history_query.get_by_external_id(ChatPlatform.DISCORD, "100")
    assert is_ok(found) and found.value == message
    missing = await chat_history_query.get_by_external_id(ChatPlatform.LINE, "100")
    assert is_ok(missing) and missing.value is None
