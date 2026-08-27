"""Chat aggregate root with TPH (Table Per Hierarchy) support."""

from __future__ import annotations

from abc import ABC
from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects import ChatId, ChatType, MessageContent, Version


@dataclass(kw_only=True, slots=True)
class Chat(ABC):
    """Base Chat aggregate root using Table Per Hierarchy inheritance.

    This is an abstract base class for all chat types (Discord, LINE, etc).
    Each aggregate instance represents one received or sent message. Concrete
    implementations (DiscordChat, LineChat) provide platform-specific context.

    Implements IAuditable: timestamps are infrastructure concerns but exposed
    as read-only fields for auditing and display purposes. The repository layer
    automatically manages created_at and updated_at.

    Implements IVersionable: optimistic locking via version field, which is
    automatically managed by the repository layer during updates.
    """

    _id: ChatId = field(
        init=False,
        default_factory=lambda: ChatId.generate().expect(
            "ChatId.generate should succeed"
        ),
    )
    _type: ChatType  # Discriminator column for ORM
    _message_content: MessageContent
    _version: Version = field(init=False, default_factory=lambda: Version(0))
    _created_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))
    _updated_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))

    @property
    def id(self) -> ChatId:
        return self._id

    @property
    def type(self) -> ChatType:
        return self._type

    @property
    def message_content(self) -> MessageContent:
        return self._message_content

    @property
    def version(self) -> Version:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at


@dataclass(kw_only=True, slots=True)
class DiscordChat(Chat):
    """Discord chat aggregate.

    Represents one Discord message where the bot receives or sends content.
    Stores Discord-specific identifiers like guild_id and channel_id.
    """

    _discord_guild_id: str  # Discord guild (server) ID
    _discord_channel_id: str  # Discord channel ID

    @classmethod
    def create(
        cls,
        guild_id: str,
        channel_id: str,
        message_content: MessageContent,
    ) -> DiscordChat:
        """Factory method to create a new Discord message chat aggregate.

        Args:
            guild_id: Discord guild (server) ID
            channel_id: Discord channel ID
            message_content: Content payload for this message

        Returns:
            New DiscordChat instance
        """
        return cls(
            _type=ChatType.DISCORD,
            _message_content=message_content,
            _discord_guild_id=guild_id,
            _discord_channel_id=channel_id,
        )

    @property
    def discord_guild_id(self) -> str:
        return self._discord_guild_id

    @property
    def discord_channel_id(self) -> str:
        return self._discord_channel_id


@dataclass(kw_only=True, slots=True)
class LineChat(Chat):
    """LINE chat aggregate.

    Represents one LINE message where the bot receives or sends content.
    Stores LINE-specific identifiers.
    """

    _line_user_id: str  # LINE user ID (for 1-on-1 chats)
    _line_group_id: str | None = None  # LINE group ID (for group chats)
    _line_room_id: str | None = None  # LINE room ID (for room chats)

    @classmethod
    def create_user_chat(
        cls,
        line_user_id: str,
        message_content: MessageContent,
    ) -> LineChat:
        """Factory method to create a new LINE 1-on-1 message chat aggregate.

        Args:
            line_user_id: LINE user ID
            message_content: Content payload for this message

        Returns:
            New LineChat instance for user chat
        """
        return cls(
            _type=ChatType.LINE,
            _message_content=message_content,
            _line_user_id=line_user_id,
            _line_group_id=None,
            _line_room_id=None,
        )

    @classmethod
    def create_group_chat(
        cls,
        line_user_id: str,
        line_group_id: str,
        message_content: MessageContent,
    ) -> LineChat:
        """Factory method to create a new LINE group message chat aggregate.

        Args:
            line_user_id: LINE user ID
            line_group_id: LINE group ID
            message_content: Content payload for this message

        Returns:
            New LineChat instance for group chat
        """
        return cls(
            _type=ChatType.LINE,
            _message_content=message_content,
            _line_user_id=line_user_id,
            _line_group_id=line_group_id,
            _line_room_id=None,
        )

    @classmethod
    def create_room_chat(
        cls,
        line_user_id: str,
        line_room_id: str,
        message_content: MessageContent,
    ) -> LineChat:
        """Factory method to create a new LINE room message chat aggregate.

        Args:
            line_user_id: LINE user ID
            line_room_id: LINE room ID
            message_content: Content payload for this message

        Returns:
            New LineChat instance for room chat
        """
        return cls(
            _type=ChatType.LINE,
            _message_content=message_content,
            _line_user_id=line_user_id,
            _line_group_id=None,
            _line_room_id=line_room_id,
        )

    @property
    def line_user_id(self) -> str:
        return self._line_user_id

    @property
    def line_group_id(self) -> str | None:
        return self._line_group_id

    @property
    def line_room_id(self) -> str | None:
        return self._line_room_id

    def is_user_chat(self) -> bool:
        """Check if this is a 1-on-1 user chat."""
        return self._line_group_id is None and self._line_room_id is None

    def is_group_chat(self) -> bool:
        """Check if this is a group chat."""
        return self._line_group_id is not None

    def is_room_chat(self) -> bool:
        """Check if this is a room chat."""
        return self._line_room_id is not None
