"""Speech publisher port."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from flow_res import Result

from app.contracts.messages.speech_message import CharacterSpeechMessage
from app.domain.value_objects import DiscordConversationScope


class SpeechPublishErrorType(Enum):
    """Types of speech publishing errors."""

    INVALID_PAYLOAD = auto()
    DELIVERY_FAILED = auto()


@dataclass(frozen=True)
class SpeechPublishError(Exception):
    """Represents an error during speech publication."""

    type: SpeechPublishErrorType
    message: str


class ISpeechPublisher(ABC):
    """Abstract speech publisher used by application layers."""

    @abstractmethod
    async def resume(
        self,
        scope: DiscordConversationScope,
        source_message_id: str,
        delivery_channel_id: str,
    ) -> Result[bool, SpeechPublishError]:
        """Resume a known response without regenerating it; False means no plan exists."""
        pass

    @abstractmethod
    async def publish(
        self,
        message: CharacterSpeechMessage,
    ) -> Result[None, SpeechPublishError]:
        """Publish a character speech message to the destination."""
        pass
