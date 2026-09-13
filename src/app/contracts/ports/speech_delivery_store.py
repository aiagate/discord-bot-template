"""Durability boundary for character delivery progress and chat history."""

from abc import ABC, abstractmethod

from flow_res import Result

from app.contracts.messages.speech_message import PublishedSpeech, SpeechDeliveryPlan
from app.domain.repositories import RepositoryError
from app.domain.value_objects import DiscordConversationScope


class ISpeechDeliveryStore(ABC):
    """Persist delivery progress and its confirmed chat message atomically."""

    @abstractmethod
    async def get(
        self, source_message_id: str
    ) -> Result[SpeechDeliveryPlan | None, RepositoryError]:
        """Read the response plan for one provider message ID."""
        pass

    @abstractmethod
    async def save(
        self, plan: SpeechDeliveryPlan, receipt: PublishedSpeech | None = None
    ) -> Result[None, RepositoryError]:
        """Save progress together with an optional confirmed message, idempotently."""
        pass

    @abstractmethod
    async def pending(
        self, scope: DiscordConversationScope
    ) -> Result[list[SpeechDeliveryPlan], RepositoryError]:
        """Read unfinished responses for one destination in creation order."""
        pass
