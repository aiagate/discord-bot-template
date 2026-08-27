"""Tests for Chat aggregate with TPH inheritance."""

from datetime import UTC, datetime

import pytest
from flow_res import is_err, is_ok

from app.domain.aggregates.chat import Chat, DiscordChat, LineChat
from app.domain.value_objects import (
    ChatId,
    ChatType,
    MassageContent,
    MessageContent,
    MessageContentType,
)


class TestChatType:
    """Tests for ChatType value object."""

    def test_chat_type_discord(self) -> None:
        """Test DISCORD chat type."""
        result = ChatType.from_primitive("DISCORD")
        assert is_ok(result)
        chat_type = result.expect("ChatType.from_primitive should succeed")
        assert chat_type == ChatType.DISCORD
        assert chat_type.to_primitive() == "DISCORD"

    def test_chat_type_line(self) -> None:
        """Test LINE chat type."""
        result = ChatType.from_primitive("LINE")
        assert is_ok(result)
        chat_type = result.expect("ChatType.from_primitive should succeed")
        assert chat_type == ChatType.LINE
        assert chat_type.to_primitive() == "LINE"

    def test_chat_type_case_insensitive(self) -> None:
        """Test that ChatType is case insensitive."""
        result_lower = ChatType.from_primitive("discord")
        assert is_ok(result_lower)
        assert result_lower.expect("").to_primitive() == "DISCORD"

    def test_chat_type_empty_raises_error(self) -> None:
        """Test that empty string raises error."""
        result = ChatType.from_primitive("")
        assert is_err(result)
        assert "Chat type cannot be empty" in str(result.error)

    def test_chat_type_invalid_raises_error(self) -> None:
        """Test that invalid chat type raises error."""
        result = ChatType.from_primitive("INVALID")
        assert is_err(result)
        assert "Invalid chat type" in str(result.error)


class TestMessageContent:
    """Tests for message content value object."""

    @pytest.mark.parametrize(
        ("content", "expected_type", "expected_payload"),
        [
            (MessageContent.text("hello"), MessageContentType.TEXT, {"text": "hello"}),
            (
                MessageContent.image(
                    image_id="image-1", url="https://example.com/1.png"
                ),
                MessageContentType.IMAGE,
                {"image_id": "image-1", "url": "https://example.com/1.png"},
            ),
            (
                MessageContent.sticker(sticker_id="sticker-1", package_id="package-1"),
                MessageContentType.STICKER,
                {"sticker_id": "sticker-1", "package_id": "package-1"},
            ),
            (MessageContent.emoji("👍"), MessageContentType.EMOJI, {"emoji": "👍"}),
        ],
    )
    def test_supported_message_content_types(
        self,
        content: MessageContent,
        expected_type: MessageContentType,
        expected_payload: dict[str, str],
    ) -> None:
        """Test supported message content variants."""
        assert content.type == expected_type
        assert content.payload == expected_payload
        assert content.to_primitive() == {
            "type": expected_type.value,
            "payload": expected_payload,
        }

    def test_message_content_from_primitive(self) -> None:
        """Test restoring message content from persistence payload."""
        result = MessageContent.from_primitive(
            {
                "type": "text",
                "payload": {"text": "hello"},
            }
        )

        assert is_ok(result)
        content = result.expect("MessageContent.from_primitive should succeed")
        assert content == MessageContent.text("hello")

    def test_message_content_rejects_invalid_type(self) -> None:
        """Test rejecting invalid content type."""
        result = MessageContent.from_primitive(
            {
                "type": "audio",
                "payload": {"audio_id": "audio-1"},
            }
        )

        assert is_err(result)
        assert "Invalid message content type" in str(result.error)

    def test_massage_content_alias_matches_message_content(self) -> None:
        """Test typo-compatible MassageContent alias."""
        assert MassageContent.text("hello") == MessageContent.text("hello")


class TestChatId:
    """Tests for ChatId value object."""

    def test_generate_chat_id(self) -> None:
        """Test generating a new ChatId."""
        result = ChatId.generate()
        assert is_ok(result)
        chat_id = result.expect("ChatId.generate should succeed")
        assert isinstance(chat_id, ChatId)

    def test_chat_id_to_primitive_returns_string(self) -> None:
        """Test ChatId to_primitive returns string."""
        result = ChatId.generate()
        assert is_ok(result)
        chat_id = result.expect("ChatId.generate should succeed")
        primitive = chat_id.to_primitive()
        assert isinstance(primitive, str)
        assert len(primitive) == 26

    def test_chat_id_from_primitive(self) -> None:
        """Test ChatId from_primitive."""
        generated = ChatId.generate().expect("ChatId.generate should succeed")
        primitive = generated.to_primitive()

        result = ChatId.from_primitive(primitive)
        assert is_ok(result)
        restored = result.expect("ChatId.from_primitive should succeed")
        assert restored == generated


class TestDiscordChat:
    """Tests for DiscordChat aggregate."""

    def test_create_discord_chat_message(self) -> None:
        """Test creating a Discord chat message."""
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.text("hello"),
        )

        assert discord_chat.type == ChatType.DISCORD
        assert discord_chat.discord_guild_id == "123456789"
        assert discord_chat.discord_channel_id == "987654321"
        assert discord_chat.message_content == MessageContent.text("hello")
        assert isinstance(discord_chat.id, ChatId)
        assert isinstance(discord_chat.created_at, datetime)
        assert isinstance(discord_chat.updated_at, datetime)

    def test_discord_chat_timestamps_use_utc(self) -> None:
        """Test that Discord chat timestamps use UTC timezone."""
        before = datetime.now(UTC)
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.text("hello"),
        )
        after = datetime.now(UTC)

        assert before <= discord_chat.created_at <= after
        assert before <= discord_chat.updated_at <= after

    def test_discord_chat_version_starts_at_zero(self) -> None:
        """Test that version starts at 0."""
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.text("hello"),
        )
        assert discord_chat.version.to_primitive() == 0


class TestLineChat:
    """Tests for LineChat aggregate."""

    def test_create_line_user_chat_message(self) -> None:
        """Test creating a LINE user chat message."""
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.image(image_id="image-1"),
        )

        assert line_chat.type == ChatType.LINE
        assert line_chat.message_content.type == MessageContentType.IMAGE
        assert line_chat.line_user_id == "U123456789"
        assert line_chat.line_group_id is None
        assert line_chat.line_room_id is None
        assert line_chat.is_user_chat()
        assert not line_chat.is_group_chat()
        assert not line_chat.is_room_chat()

    def test_create_line_group_chat_message(self) -> None:
        """Test creating a LINE group chat message."""
        line_chat = LineChat.create_group_chat(
            line_user_id="U123456789",
            line_group_id="C123456789",
            message_content=MessageContent.sticker(sticker_id="sticker-1"),
        )

        assert line_chat.type == ChatType.LINE
        assert line_chat.message_content.type == MessageContentType.STICKER
        assert line_chat.line_user_id == "U123456789"
        assert line_chat.line_group_id == "C123456789"
        assert line_chat.line_room_id is None
        assert not line_chat.is_user_chat()
        assert line_chat.is_group_chat()
        assert not line_chat.is_room_chat()

    def test_create_line_room_chat_message(self) -> None:
        """Test creating a LINE room chat message."""
        line_chat = LineChat.create_room_chat(
            line_user_id="U123456789",
            line_room_id="R123456789",
            message_content=MessageContent.emoji("👍"),
        )

        assert line_chat.type == ChatType.LINE
        assert line_chat.message_content.type == MessageContentType.EMOJI
        assert line_chat.line_user_id == "U123456789"
        assert line_chat.line_group_id is None
        assert line_chat.line_room_id == "R123456789"
        assert not line_chat.is_user_chat()
        assert not line_chat.is_group_chat()
        assert line_chat.is_room_chat()

    def test_line_chat_timestamps_use_utc(self) -> None:
        """Test that LINE chat timestamps use UTC timezone."""
        before = datetime.now(UTC)
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.text("hello"),
        )
        after = datetime.now(UTC)

        assert before <= line_chat.created_at <= after
        assert before <= line_chat.updated_at <= after

    def test_line_chat_version_starts_at_zero(self) -> None:
        """Test that version starts at 0."""
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.text("hello"),
        )
        assert line_chat.version.to_primitive() == 0


class TestChatAggregateProperties:
    """Tests for Chat aggregate base properties."""

    def test_discord_chat_is_instance_of_chat(self) -> None:
        """Test that DiscordChat is an instance of Chat."""
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.text("hello"),
        )
        assert isinstance(discord_chat, Chat)

    def test_line_chat_is_instance_of_chat(self) -> None:
        """Test that LineChat is an instance of Chat."""
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.text("hello"),
        )
        assert isinstance(line_chat, Chat)

    def test_discord_and_line_chat_have_different_ids(self) -> None:
        """Test that different chat messages have different IDs."""
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.text("hello"),
        )
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.text("hello"),
        )

        assert discord_chat.id != line_chat.id
