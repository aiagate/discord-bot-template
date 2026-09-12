"""Tests for conversation-scoped ChatMessage history queries."""

from datetime import UTC, datetime, timedelta

import pytest
from flow_res import is_ok

from app.contracts.ports import IChatHistoryQuery, IUnitOfWork
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.value_objects import (
    AuthorKind,
    DiscordConversationScope,
    LineConversationScope,
    MessageContent,
)


async def _save_message(uow: IUnitOfWork, message: ChatMessage) -> None:
    """Persist one message for query tests."""
    async with uow:
        repository = uow.GetRepository(ChatMessage)
        save_result = await repository.add(message)
        assert is_ok(save_result)
        commit_result = await uow.commit()
        assert is_ok(commit_result)


@pytest.mark.anyio
async def test_history_is_scoped_to_one_discord_conversation(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """Discord history excludes messages from another guild or channel."""
    start = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    await _save_message(
        uow,
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-1",
            external_sender_id="user-1",
            content=MessageContent.text("first"),
            occurred_at=start,
        ),
    )
    await _save_message(
        uow,
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-2",
            external_sender_id="user-1",
            content=MessageContent.text("other channel"),
            occurred_at=start + timedelta(minutes=1),
        ),
    )
    await _save_message(
        uow,
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-1",
            external_sender_id="user-2",
            content=MessageContent.text("second"),
            occurred_at=start + timedelta(minutes=2),
        ),
    )

    result = await chat_history_query.get_recent_history(
        DiscordConversationScope(guild_id="guild-1", channel_id="channel-1"),
        limit=10,
    )

    assert is_ok(result)
    assert [item.content.payload["text"] for item in result.value] == [
        "first",
        "second",
    ]


@pytest.mark.anyio
async def test_recent_discord_user_messages_cover_a_guild_without_bots(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """Guild-wide candidates include users from every channel, not bot posts."""
    start = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    messages = (
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-1",
            external_sender_id="user-1",
            content=MessageContent.text("first"),
            occurred_at=start,
        ),
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-2",
            external_sender_id="poll-bot",
            author_kind=AuthorKind.BOT,
            content=MessageContent.text("ignore bot"),
            occurred_at=start + timedelta(minutes=1),
        ),
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-2",
            external_sender_id="user-2",
            content=MessageContent.text("latest"),
            occurred_at=start + timedelta(minutes=2),
        ),
    )
    for message in messages:
        await _save_message(uow, message)

    result = await chat_history_query.get_recent_discord_user_messages(
        "guild-1", limit=10
    )

    assert is_ok(result)
    assert [item.content.payload["text"] for item in result.value] == [
        "first",
        "latest",
    ]


@pytest.mark.anyio
async def test_history_keeps_line_user_group_and_room_scopes_separate(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """LINE history distinguishes user, group, and room conversations."""
    messages = [
        ChatMessage.create_line_user(
            line_user_id="line-user-1",
            external_sender_id="line-user-1",
            content=MessageContent.text("user"),
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        ),
        ChatMessage.create_line_group(
            line_group_id="line-group-1",
            external_sender_id="line-user-1",
            content=MessageContent.text("group"),
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        ),
        ChatMessage.create_line_room(
            line_room_id="line-room-1",
            external_sender_id="line-user-1",
            content=MessageContent.text("room"),
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        ),
    ]
    for message in messages:
        await _save_message(uow, message)

    group_result = await chat_history_query.get_recent_history(
        LineConversationScope.group("line-group-1"),
        limit=10,
    )
    room_result = await chat_history_query.get_recent_history(
        LineConversationScope.room("line-room-1"),
        limit=10,
    )

    assert is_ok(group_result)
    assert is_ok(room_result)
    assert [item.content.payload["text"] for item in group_result.value] == ["group"]
    assert [item.content.payload["text"] for item in room_result.value] == ["room"]


@pytest.mark.anyio
async def test_history_limit_returns_newest_messages_in_chronological_order(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """A limited history contains the newest messages ordered oldest to newest."""
    start = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    for index in range(5):
        await _save_message(
            uow,
            ChatMessage.create_discord(
                guild_id="guild-1",
                channel_id="channel-1",
                external_sender_id="user-1",
                content=MessageContent.text(f"message-{index}"),
                occurred_at=start + timedelta(minutes=index),
            ),
        )

    result = await chat_history_query.get_recent_history(
        DiscordConversationScope(guild_id="guild-1", channel_id="channel-1"),
        limit=3,
    )

    assert is_ok(result)
    assert [item.content.payload["text"] for item in result.value] == [
        "message-2",
        "message-3",
        "message-4",
    ]


@pytest.mark.anyio
async def test_sequential_queries_use_isolated_read_sessions(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """A query call closes its session before the next call begins."""
    await _save_message(
        uow,
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-1",
            external_sender_id="user-1",
            content=MessageContent.text("one"),
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        ),
    )

    first_result = await chat_history_query.get_recent_history(
        DiscordConversationScope(guild_id="guild-1", channel_id="channel-1"),
        limit=10,
    )
    second_result = await chat_history_query.get_recent_history(
        DiscordConversationScope(guild_id="guild-1", channel_id="channel-1"),
        limit=10,
    )

    assert is_ok(first_result)
    assert is_ok(second_result)
    assert [item.content.payload["text"] for item in first_result.value] == ["one"]
    assert [item.content.payload["text"] for item in second_result.value] == ["one"]


@pytest.mark.anyio
async def test_history_cutoff_is_applied_before_limit_and_excludes_later_posts(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    start = datetime(2026, 9, 12, tzinfo=UTC)
    scope = DiscordConversationScope(guild_id="456", channel_id="123")
    source = ChatMessage.create_discord(
        guild_id="456",
        channel_id="123",
        external_sender_id="alice",
        content=MessageContent.text("現在の質問"),
        occurred_at=start + timedelta(seconds=1),
        external_message_id="100",
        author_name="Alice",
    )
    await _save_message(
        uow,
        ChatMessage.create_discord(
            guild_id="456",
            channel_id="123",
            external_sender_id="poll-bot",
            content=MessageContent.text("アンケート: 賛成8、反対2"),
            occurred_at=start,
            author_kind=AuthorKind.BOT,
            external_message_id="99",
            author_name="Poll Bot",
        ),
    )
    await _save_message(uow, source)
    for index in range(25):
        await _save_message(
            uow,
            ChatMessage.create_discord(
                guild_id="456",
                channel_id="123",
                external_sender_id="bob",
                content=MessageContent.text(f"将来の発言{index}"),
                occurred_at=start + timedelta(seconds=2 + index),
            ),
        )
    result = await chat_history_query.get_recent_history(
        scope,
        limit=20,
        before=(source.occurred_at, source.id.to_primitive()),
    )
    assert is_ok(result)
    assert len(result.value) == 1
    assert result.value[0].author_kind is AuthorKind.BOT
    assert result.value[0].author_name == "Poll Bot"
    assert result.value[0].content.payload["text"] == "アンケート: 賛成8、反対2"
