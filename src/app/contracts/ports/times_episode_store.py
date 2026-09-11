"""Application port for Times episode plan persistence."""

from abc import ABC, abstractmethod
from datetime import datetime

from flow_res import Result

from app.contracts.messages.times_message import TimesEpisodePlan
from app.domain.repositories import RepositoryError
from app.domain.value_objects import DiscordConversationScope


class ITimesEpisodeStore(ABC):
    """Durable storage for Times episodes and board delivery progress."""

    @abstractmethod
    async def get(
        self, source_message_id: str
    ) -> Result[TimesEpisodePlan | None, RepositoryError]:
        """Read a persisted Times episode plan by its source message ID."""
        pass

    @abstractmethod
    async def save(self, plan: TimesEpisodePlan) -> Result[None, RepositoryError]:
        """Persist or update an episode plan."""
        pass

    @abstractmethod
    async def pending(
        self, destination: DiscordConversationScope
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        """Return unfinished plans for one board in order of creation."""
        pass

    @abstractmethod
    async def get_recent_completed(
        self,
        destination: DiscordConversationScope,
        limit: int = 5,
        *,
        before: datetime | None = None,
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        """Return recent completed plans belonging to one board."""
        pass
