"""Immutable chat message aggregate."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects import (
    AuthorKind,
    ChatPlatform,
    ConversationScope,
    DiscordConversationScope,
    ExternalActorId,
    LineConversationScope,
    MessageContent,
    MessageId,
)


def _as_platform(value: ChatPlatform | str) -> ChatPlatform:
    """Convert a platform input to its domain value object."""
    if isinstance(value, ChatPlatform):
        return value
    return ChatPlatform.from_primitive(value).expect(
        "ChatPlatform.from_primitive should succeed"
    )


def _as_actor_id(value: ExternalActorId | str) -> ExternalActorId:
    """Convert an actor identifier input to its domain value object."""
    if isinstance(value, ExternalActorId):
        return value
    return ExternalActorId(value)


def _as_author_kind(value: AuthorKind | str) -> AuthorKind:
    """Convert an author kind input to its domain value object."""
    if isinstance(value, AuthorKind):
        return value
    return AuthorKind.from_primitive(value).expect(
        "AuthorKind.from_primitive should succeed"
    )


def _normalize_occurred_at(value: object) -> datetime:
    """Normalize an occurred timestamp to an aware UTC datetime."""
    if not isinstance(value, datetime):
        raise ValueError("Occurred timestamp must be a datetime.")
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("Occurred timestamp must be timezone-aware.")
    return value.astimezone(UTC)


@dataclass(frozen=True, kw_only=True, slots=True)
class ChatMessage:
    """One immutable, append-only message from an external platform.

    A message is the consistency boundary. Conversation history is retrieved
    by querying messages for a ``ConversationScope``; there is intentionally no
    conversation aggregate or platform-specific message subclass.
    """

    _id: MessageId = field(
        default_factory=lambda: MessageId.generate().expect(
            "MessageId.generate should succeed"
        )
    )
    _platform: ChatPlatform
    _conversation_scope: ConversationScope
    _external_sender_id: ExternalActorId
    _author_kind: AuthorKind
    _content: MessageContent
    _occurred_at: datetime

    def __eq__(self, other: object) -> bool:
        """Compare message identity, independently of its content."""
        if not isinstance(other, ChatMessage) or type(self) is not type(other):
            return NotImplemented
        return self.id == other.id

    def __hash__(self) -> int:
        """Hash the same immutable identity used by equality."""
        return hash((type(self), self.id))

    def __post_init__(self) -> None:
        """Validate the complete message consistency boundary."""
        if self._conversation_scope.platform != self._platform:
            raise ValueError(
                "Chat message platform and conversation scope platform must match."
            )

        object.__setattr__(
            self,
            "_occurred_at",
            _normalize_occurred_at(self._occurred_at),
        )

    @classmethod
    def create(
        cls,
        *,
        platform: ChatPlatform | str,
        conversation_scope: ConversationScope,
        external_sender_id: ExternalActorId | str,
        author_kind: AuthorKind | str,
        content: MessageContent,
        occurred_at: datetime,
        message_id: MessageId | None = None,
    ) -> ChatMessage:
        """Create a new immutable chat message."""
        return cls(
            _id=message_id
            or MessageId.generate().expect("MessageId.generate should succeed"),
            _platform=_as_platform(platform),
            _conversation_scope=conversation_scope,
            _external_sender_id=_as_actor_id(external_sender_id),
            _author_kind=_as_author_kind(author_kind),
            _content=content,
            _occurred_at=occurred_at,
        )

    @classmethod
    def create_discord(
        cls,
        *,
        guild_id: str,
        channel_id: str,
        external_sender_id: ExternalActorId | str,
        content: MessageContent,
        author_kind: AuthorKind | str = AuthorKind.USER,
        occurred_at: datetime,
        message_id: MessageId | None = None,
    ) -> ChatMessage:
        """Create a message scoped to a Discord guild and channel."""
        return cls.create(
            platform=ChatPlatform.DISCORD,
            conversation_scope=DiscordConversationScope(
                guild_id=guild_id,
                channel_id=channel_id,
            ),
            external_sender_id=external_sender_id,
            author_kind=author_kind,
            content=content,
            occurred_at=occurred_at,
            message_id=message_id,
        )

    @classmethod
    def create_line(
        cls,
        *,
        conversation_scope: LineConversationScope,
        external_sender_id: ExternalActorId | str,
        content: MessageContent,
        author_kind: AuthorKind | str = AuthorKind.USER,
        occurred_at: datetime,
        message_id: MessageId | None = None,
    ) -> ChatMessage:
        """Create a message scoped to a LINE conversation."""
        return cls.create(
            platform=ChatPlatform.LINE,
            conversation_scope=conversation_scope,
            external_sender_id=external_sender_id,
            author_kind=author_kind,
            content=content,
            occurred_at=occurred_at,
            message_id=message_id,
        )

    @classmethod
    def create_line_user(
        cls,
        *,
        line_user_id: str,
        external_sender_id: ExternalActorId | str,
        content: MessageContent,
        author_kind: AuthorKind | str = AuthorKind.USER,
        occurred_at: datetime,
        message_id: MessageId | None = None,
    ) -> ChatMessage:
        """Create a message for a one-to-one LINE conversation."""
        return cls.create_line(
            conversation_scope=LineConversationScope.user(line_user_id),
            external_sender_id=external_sender_id,
            content=content,
            author_kind=author_kind,
            occurred_at=occurred_at,
            message_id=message_id,
        )

    @classmethod
    def create_line_group(
        cls,
        *,
        line_group_id: str,
        external_sender_id: ExternalActorId | str,
        content: MessageContent,
        author_kind: AuthorKind | str = AuthorKind.USER,
        occurred_at: datetime,
        message_id: MessageId | None = None,
    ) -> ChatMessage:
        """Create a message for a LINE group conversation."""
        return cls.create_line(
            conversation_scope=LineConversationScope.group(line_group_id),
            external_sender_id=external_sender_id,
            content=content,
            author_kind=author_kind,
            occurred_at=occurred_at,
            message_id=message_id,
        )

    @classmethod
    def create_line_room(
        cls,
        *,
        line_room_id: str,
        external_sender_id: ExternalActorId | str,
        content: MessageContent,
        author_kind: AuthorKind | str = AuthorKind.USER,
        occurred_at: datetime,
        message_id: MessageId | None = None,
    ) -> ChatMessage:
        """Create a message for a LINE room conversation."""
        return cls.create_line(
            conversation_scope=LineConversationScope.room(line_room_id),
            external_sender_id=external_sender_id,
            content=content,
            author_kind=author_kind,
            occurred_at=occurred_at,
            message_id=message_id,
        )

    @classmethod
    def restore(
        cls,
        *,
        message_id: MessageId,
        platform: ChatPlatform,
        conversation_scope: ConversationScope,
        external_sender_id: ExternalActorId,
        author_kind: AuthorKind,
        content: MessageContent,
        occurred_at: datetime,
    ) -> ChatMessage:
        """Restore a message from persistence without adding update state."""
        return cls(
            _id=message_id,
            _platform=platform,
            _conversation_scope=conversation_scope,
            _external_sender_id=external_sender_id,
            _author_kind=author_kind,
            _content=content,
            _occurred_at=occurred_at,
        )

    @property
    def id(self) -> MessageId:
        """Return the message identifier."""
        return self._id

    @property
    def is_append_only(self) -> bool:
        """Return whether this message supports only insertion."""
        return True

    @property
    def platform(self) -> ChatPlatform:
        """Return the source platform."""
        return self._platform

    @property
    def conversation_scope(self) -> ConversationScope:
        """Return the conversation scope used for history queries."""
        return self._conversation_scope

    @property
    def external_sender_id(self) -> ExternalActorId:
        """Return the external platform identity of the author."""
        return self._external_sender_id

    @property
    def author_kind(self) -> AuthorKind:
        """Return whether the author is a user, bot, or system."""
        return self._author_kind

    @property
    def content(self) -> MessageContent:
        """Return the message content."""
        return self._content

    @property
    def occurred_at(self) -> datetime:
        """Return the time at which the external message occurred."""
        return self._occurred_at
