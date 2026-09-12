"""Messages for character speech publishing."""

from dataclasses import dataclass
from datetime import datetime

from app.domain.value_objects import DiscordConversationScope


@dataclass(frozen=True, slots=True)
class CharacterSpeechMessage:
    """Message payload for publishing character speech via webhook.

    For a forum webhook, ``conversation_scope`` identifies the post thread and
    ``delivery_channel_id`` identifies its parent forum channel.
    """

    content: str
    username: str
    conversation_scope: DiscordConversationScope
    source_message_id: str
    delivery_channel_id: str
    avatar_url: str | None = None
    user_id: str | None = None


@dataclass(frozen=True, slots=True)
class PublishedSpeech:
    """Discord's confirmed identity, content and time for one delivered part."""

    external_message_id: str
    conversation_scope: DiscordConversationScope
    external_sender_id: str
    username: str
    content: str
    occurred_at: datetime
    source_message_id: str
    user_id: str | None = None


@dataclass(frozen=True, slots=True)
class SpeechDeliveryPlan:
    """Durable progress for one response, including a potentially unacknowledged send."""

    source_message_id: str
    conversation_scope: DiscordConversationScope
    username: str
    avatar_url: str | None
    parts: tuple[str, ...]
    delivery_channel_id: str
    user_id: str | None = None
    delivered: tuple[PublishedSpeech, ...] = ()
    attempt_started_at: datetime | None = None
    failure: str | None = None

    @property
    def complete(self) -> bool:
        """Return whether all parts have been confirmed and persisted."""
        return len(self.delivered) == len(self.parts)
