"""Tests for the immutable ChatMessage aggregate and scope value objects."""

from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.domain.aggregates.chat_message import ChatMessage
from app.domain.value_objects import (
    AuthorKind,
    ChatPlatform,
    DiscordConversationScope,
    ExternalActorId,
    LineConversationScope,
    MessageContent,
    MessageContentType,
    MessageId,
)


def test_message_identity_and_hash_depend_on_id_not_content() -> None:
    """Restoration uses identity equality without treating content as equal."""
    message = ChatMessage.create_discord(
        guild_id="guild-1",
        channel_id="channel-1",
        external_sender_id="sender-1",
        content=MessageContent.text("original"),
        occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
    )
    restored = ChatMessage.restore(
        message_id=message.id,
        platform=message.platform,
        conversation_scope=message.conversation_scope,
        external_sender_id=message.external_sender_id,
        author_kind=message.author_kind,
        content=MessageContent.text("different representation"),
        occurred_at=message.occurred_at,
    )
    another = ChatMessage.restore(
        message_id=MessageId.generate().expect("valid id"),
        platform=message.platform,
        conversation_scope=message.conversation_scope,
        external_sender_id=message.external_sender_id,
        author_kind=message.author_kind,
        content=message.content,
        occurred_at=message.occurred_at,
    )

    assert message is not restored
    assert message == restored
    assert restored == message
    assert message.content != restored.content
    assert hash(message) == hash(restored)
    assert len({message, restored, another}) == 2
    assert message != another
    assert message != object()


def test_discord_message_captures_all_message_data() -> None:
    """A Discord message stores all required domain data."""
    occurred_at = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)

    message = ChatMessage.create_discord(
        guild_id="guild-1",
        channel_id="channel-1",
        external_sender_id="discord-user-1",
        author_kind=AuthorKind.USER,
        content=MessageContent.text("hello"),
        occurred_at=occurred_at,
    )

    assert message.platform is ChatPlatform.DISCORD
    assert message.conversation_scope == DiscordConversationScope(
        guild_id="guild-1",
        channel_id="channel-1",
    )
    assert message.external_sender_id == ExternalActorId("discord-user-1")
    assert message.author_kind is AuthorKind.USER
    assert message.content == MessageContent.text("hello")
    assert message.occurred_at == occurred_at
    assert message.id.to_primitive()
    assert not hasattr(message, "version")
    assert not hasattr(message, "updated_at")


def test_chat_message_is_immutable() -> None:
    """Message fields cannot be changed after creation."""
    message = ChatMessage.create_discord(
        guild_id="guild-1",
        channel_id="channel-1",
        external_sender_id="discord-user-1",
        content=MessageContent.text("hello"),
        occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
    )

    with pytest.raises(FrozenInstanceError):
        message._content = MessageContent.text("changed")  # type: ignore[misc]


def test_message_content_protects_nested_payload_from_input_mutation() -> None:
    """Message content copies nested constructor data before storing it."""
    payload = {"metadata": {"labels": ["original"]}}
    content = MessageContent(_type=MessageContentType.TEXT, _payload=payload)

    payload["metadata"]["labels"].append("changed")

    assert content.payload == {"metadata": {"labels": ["original"]}}


def test_message_content_returns_independent_nested_payload_copies() -> None:
    """Message content accessors cannot mutate the stored nested payload."""
    content = MessageContent(
        _type=MessageContentType.TEXT,
        _payload={"metadata": {"labels": ["original"]}},
    )

    payload = content.payload
    payload["metadata"]["labels"].append("changed")
    primitive = content.to_primitive()
    primitive["payload"]["metadata"]["labels"].append("changed")

    assert content.payload == {"metadata": {"labels": ["original"]}}


@pytest.mark.parametrize(
    ("message", "expected_scope"),
    [
        (
            ChatMessage.create_line_user(
                line_user_id="line-user-1",
                external_sender_id="line-user-1",
                content=MessageContent.text("user"),
                occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
            ),
            LineConversationScope.user("line-user-1"),
        ),
        (
            ChatMessage.create_line_group(
                line_group_id="line-group-1",
                external_sender_id="line-user-1",
                content=MessageContent.text("group"),
                occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
            ),
            LineConversationScope.group("line-group-1"),
        ),
        (
            ChatMessage.create_line_room(
                line_room_id="line-room-1",
                external_sender_id="line-user-1",
                content=MessageContent.text("room"),
                occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
            ),
            LineConversationScope.room("line-room-1"),
        ),
    ],
)
def test_line_message_captures_each_scope_kind(
    message: ChatMessage,
    expected_scope: LineConversationScope,
) -> None:
    """LINE user, group, and room locators remain distinct."""
    assert message.platform is ChatPlatform.LINE
    assert message.conversation_scope == expected_scope
    assert message.external_sender_id == ExternalActorId("line-user-1")


def test_line_scope_rejects_multiple_locators() -> None:
    """A LINE message cannot be both a group and room conversation."""
    with pytest.raises(ValueError, match="exactly one"):
        LineConversationScope(line_user_id="user-1", line_group_id="group-1")


def test_platform_and_scope_must_match() -> None:
    """A message cannot label a LINE scope as Discord."""
    with pytest.raises(ValueError, match="platform"):
        ChatMessage.create(
            platform=ChatPlatform.DISCORD,
            conversation_scope=LineConversationScope.user("line-user-1"),
            external_sender_id="line-user-1",
            author_kind=AuthorKind.USER,
            content=MessageContent.text("invalid"),
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        )


def test_occurred_at_is_normalized_to_utc() -> None:
    """An aware occurred timestamp is normalized to UTC at the domain boundary."""
    occurred_at = datetime(
        2026,
        9,
        5,
        18,
        0,
        tzinfo=timezone(timedelta(hours=9)),
    )

    message = ChatMessage.create_discord(
        guild_id="guild-1",
        channel_id="channel-1",
        external_sender_id="discord-user-1",
        content=MessageContent.text("hello"),
        occurred_at=occurred_at,
    )

    assert message.occurred_at == datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    assert message.occurred_at.tzinfo is UTC


def test_occurred_at_rejects_naive_timestamp() -> None:
    """A naive occurred timestamp is rejected instead of using local time."""
    with pytest.raises(ValueError, match="timezone-aware"):
        ChatMessage.create_discord(
            guild_id="guild-1",
            channel_id="channel-1",
            external_sender_id="discord-user-1",
            content=MessageContent.text("hello"),
            occurred_at=datetime(2026, 9, 5, 9, 0),
        )
