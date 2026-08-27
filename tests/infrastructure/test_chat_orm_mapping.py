"""Tests for Chat ORM mapping with TPH inheritance."""

from app.domain.aggregates.chat import DiscordChat, LineChat
from app.domain.value_objects import MessageContent, MessageContentType
from app.infrastructure.orm_mapping import (
    ORMMappingRegistry,
    entity_to_orm_dict,
    orm_to_entity,
)
from app.infrastructure.orm_models import ChatORM


class TestChatORMMapping:
    """Tests for Chat aggregate ORM mapping."""

    def test_entity_to_orm_dict_discord_chat(self) -> None:
        """Test converting DiscordChat entity to ORM dict."""
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.text("hello"),
        )

        orm_dict = entity_to_orm_dict(discord_chat)

        assert orm_dict["type"] == "DISCORD"
        assert orm_dict["message_content"] == {
            "type": "TEXT",
            "payload": {"text": "hello"},
        }
        assert orm_dict["discord_guild_id"] == "123456789"
        assert orm_dict["discord_channel_id"] == "987654321"
        assert "id" in orm_dict
        assert "version" in orm_dict

    def test_entity_to_orm_dict_line_chat_user(self) -> None:
        """Test converting LineChat (user) entity to ORM dict."""
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.image(image_id="image-1"),
        )

        orm_dict = entity_to_orm_dict(line_chat)

        assert orm_dict["type"] == "LINE"
        assert orm_dict["message_content"] == {
            "type": "IMAGE",
            "payload": {"image_id": "image-1"},
        }
        assert orm_dict["line_user_id"] == "U123456789"
        assert orm_dict["line_group_id"] is None
        assert orm_dict["line_room_id"] is None
        assert "id" in orm_dict
        assert "version" in orm_dict

    def test_orm_to_entity_discord_chat_orm(self) -> None:
        """Test converting ChatORM (Discord) to DiscordChat entity."""
        orm_instance = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="DISCORD",
            message_content={"type": "TEXT", "payload": {"text": "hello"}},
            version=0,
            discord_guild_id="123456789",
            discord_channel_id="987654321",
        )

        discord_chat = orm_to_entity(orm_instance, DiscordChat)

        assert isinstance(discord_chat, DiscordChat)
        assert discord_chat.type.value == "DISCORD"
        assert discord_chat.message_content == MessageContent.text("hello")
        assert discord_chat.discord_guild_id == "123456789"
        assert discord_chat.discord_channel_id == "987654321"

    def test_orm_to_entity_line_chat_orm_user(self) -> None:
        """Test converting ChatORM (LINE) to LineChat entity."""
        orm_instance = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="LINE",
            message_content={"type": "STICKER", "payload": {"sticker_id": "1"}},
            version=0,
            line_user_id="U123456789",
            line_group_id=None,
            line_room_id=None,
        )

        line_chat = orm_to_entity(orm_instance, LineChat)

        assert isinstance(line_chat, LineChat)
        assert line_chat.type.value == "LINE"
        assert line_chat.message_content == MessageContent.sticker(sticker_id="1")
        assert line_chat.line_user_id == "U123456789"
        assert line_chat.is_user_chat()

    def test_orm_registry_discord_chat_mapping(self) -> None:
        """Test ORMMappingRegistry Discord chat mapping."""
        discord_chat = DiscordChat.create(
            guild_id="123456789",
            channel_id="987654321",
            message_content=MessageContent.emoji("👍"),
        )

        orm_instance = ORMMappingRegistry.to_orm(discord_chat)
        restored = orm_to_entity(orm_instance, DiscordChat)

        assert isinstance(orm_instance, ChatORM)
        assert orm_instance.type == "DISCORD"
        assert orm_instance.message_content == {
            "type": "EMOJI",
            "payload": {"emoji": "👍"},
        }
        assert restored.id == discord_chat.id
        assert restored.message_content.type == MessageContentType.EMOJI
        assert restored.discord_guild_id == discord_chat.discord_guild_id

    def test_orm_registry_line_chat_mapping(self) -> None:
        """Test ORMMappingRegistry LINE chat mapping."""
        line_chat = LineChat.create_user_chat(
            line_user_id="U123456789",
            message_content=MessageContent.text("hello"),
        )

        orm_instance = ORMMappingRegistry.to_orm(line_chat)
        restored = orm_to_entity(orm_instance, LineChat)

        assert isinstance(orm_instance, ChatORM)
        assert orm_instance.type == "LINE"
        assert restored.line_user_id == line_chat.line_user_id
        assert restored.message_content == MessageContent.text("hello")


class TestChatTPHDiscriminator:
    """Tests for TPH discriminator functionality."""

    def test_chat_orm_has_correct_discord_discriminator(self) -> None:
        """Test that ChatORM with Discord type has correct discriminator."""
        discord_chat_orm = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="DISCORD",
            message_content={"type": "TEXT", "payload": {"text": "hello"}},
            version=0,
            discord_guild_id="123456789",
            discord_channel_id="987654321",
        )
        assert discord_chat_orm.type == "DISCORD"

    def test_chat_orm_has_correct_line_discriminator(self) -> None:
        """Test that ChatORM with LINE type has correct discriminator."""
        line_chat_orm = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="LINE",
            message_content={"type": "IMAGE", "payload": {"image_id": "1"}},
            version=0,
            line_user_id="U123456789",
        )
        assert line_chat_orm.type == "LINE"

    def test_orm_registry_maps_discord_correctly(self) -> None:
        """Test that ORMMappingRegistry correctly handles Discord chats."""
        discord_orm = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="DISCORD",
            message_content={"type": "TEXT", "payload": {"text": "hello"}},
            version=0,
            discord_guild_id="123456789",
            discord_channel_id="987654321",
        )

        restored = orm_to_entity(discord_orm, DiscordChat)
        assert isinstance(restored, DiscordChat)
        assert restored.type.value == "DISCORD"

    def test_orm_registry_maps_line_correctly(self) -> None:
        """Test that ORMMappingRegistry correctly handles LINE chats."""
        line_orm = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="LINE",
            message_content={"type": "TEXT", "payload": {"text": "hello"}},
            version=0,
            line_user_id="U123456789",
        )

        restored = orm_to_entity(line_orm, LineChat)
        assert isinstance(restored, LineChat)
        assert restored.type.value == "LINE"

    def test_registry_from_orm_picks_discord_subtype(self) -> None:
        """Test that ORMMappingRegistry.from_orm restores DiscordChat."""
        orm_instance = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="DISCORD",
            message_content={"type": "TEXT", "payload": {"text": "hello"}},
            version=0,
            discord_guild_id="123456789",
            discord_channel_id="987654321",
        )

        restored = ORMMappingRegistry.from_orm(orm_instance)

        assert isinstance(restored, DiscordChat)
        assert restored.discord_channel_id == "987654321"

    def test_registry_from_orm_picks_line_subtype(self) -> None:
        """Test that ORMMappingRegistry.from_orm restores LineChat."""
        orm_instance = ChatORM(
            id="01ARZ3NDEKTSV4RRFFQ69G5FAV",
            type="LINE",
            message_content={"type": "TEXT", "payload": {"text": "hello"}},
            version=0,
            line_user_id="U123456789",
        )

        restored = ORMMappingRegistry.from_orm(orm_instance)

        assert isinstance(restored, LineChat)
        assert restored.line_user_id == "U123456789"
