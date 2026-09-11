"""Mapping between ChatMessage and its SQLModel row."""

from datetime import UTC, datetime
from typing import Any

from flow_res import is_err
from sqlmodel import SQLModel

from app.domain.aggregates.chat_message import ChatMessage
from app.domain.value_objects import (
    AuthorKind,
    ChatPlatform,
    DiscordConversationScope,
    ExternalActorId,
    LineConversationKind,
    LineConversationScope,
    MessageContent,
    MessageId,
)
from app.infrastructure.orm_models.chat_message_orm import ChatMessageORM


def chat_message_to_orm(message: ChatMessage) -> ChatMessageORM:
    """Convert a ChatMessage into a clean chat_messages row."""
    return ChatMessageORM(
        id=message.id.to_primitive(),
        platform=message.platform.to_primitive(),
        conversation_scope=message.conversation_scope.to_primitive(),
        external_sender_id=message.external_sender_id.to_primitive(),
        author_kind=message.author_kind.to_primitive(),
        content=message.content.to_primitive(),
        occurred_at=message.occurred_at,
        external_message_id=message.external_message_id,
        author_name=message.author_name,
        reply_to_external_message_id=message.reply_to_external_message_id,
    )


def _required_scope_value(scope: dict[str, Any], key: str) -> str:
    """Read one required string from a persisted conversation scope."""
    value = scope.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(
            f"Conversation scope field '{key}' must be a non-empty string."
        )
    return value


def _scope_from_orm(
    platform: ChatPlatform,
    scope: dict[str, Any],
) -> DiscordConversationScope | LineConversationScope:
    """Restore and validate a platform-specific conversation scope."""
    persisted_platform = scope.get("platform")
    if persisted_platform != platform.to_primitive():
        raise ValueError("Conversation scope platform does not match message platform.")

    if platform is ChatPlatform.DISCORD:
        expected_keys = {"platform", "guild_id", "channel_id"}
        if set(scope) != expected_keys:
            raise ValueError("Discord conversation scope has invalid fields.")
        return DiscordConversationScope(
            guild_id=_required_scope_value(scope, "guild_id"),
            channel_id=_required_scope_value(scope, "channel_id"),
        )

    expected_keys = {"platform", "kind", "locator"}
    if set(scope) != expected_keys:
        raise ValueError("LINE conversation scope has invalid fields.")
    kind_value = _required_scope_value(scope, "kind")
    locator = _required_scope_value(scope, "locator")
    try:
        kind = LineConversationKind(kind_value)
    except ValueError as error:
        raise ValueError(f"Invalid LINE conversation kind: {kind_value}") from error

    if kind is LineConversationKind.USER:
        return LineConversationScope.user(locator)
    if kind is LineConversationKind.GROUP:
        return LineConversationScope.group(locator)
    return LineConversationScope.room(locator)


def _occurred_at_from_orm(value: datetime) -> datetime:
    """Normalize a database driver's timestamp to aware UTC."""
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def chat_message_from_orm(row: SQLModel) -> ChatMessage:
    """Convert and validate a chat_messages row as a ChatMessage."""
    if not isinstance(row, ChatMessageORM):
        raise TypeError("Expected a ChatMessageORM row.")

    platform_result = ChatPlatform.from_primitive(row.platform)
    if is_err(platform_result):
        raise ValueError(str(platform_result.error))
    platform = platform_result.value

    sender_result = ExternalActorId.from_primitive(row.external_sender_id)
    if is_err(sender_result):
        raise ValueError(str(sender_result.error))

    author_result = AuthorKind.from_primitive(row.author_kind)
    if is_err(author_result):
        raise ValueError(str(author_result.error))

    content_result = MessageContent.from_primitive(row.content)
    if is_err(content_result):
        raise ValueError(str(content_result.error))

    message_id_result = MessageId.from_primitive(row.id)
    if is_err(message_id_result):
        raise ValueError(str(message_id_result.error))

    scope = _scope_from_orm(platform, row.conversation_scope)
    return ChatMessage.restore(
        message_id=message_id_result.value,
        platform=platform,
        conversation_scope=scope,
        external_sender_id=sender_result.value,
        author_kind=author_result.value,
        content=content_result.value,
        occurred_at=_occurred_at_from_orm(row.occurred_at),
        external_message_id=row.external_message_id,
        author_name=row.author_name,
        reply_to_external_message_id=row.reply_to_external_message_id,
    )
