"""Application port for character-owned memory."""

from abc import ABC, abstractmethod
from collections.abc import Sequence
from datetime import datetime

from flow_res import Result

from app.domain.character_memory import CharacterMemory, CharacterMemorySummary
from app.domain.repositories import RepositoryError


class ICharacterMemoryStore(ABC):
    """Read and idempotently save memory for each configured character."""

    @abstractmethod
    async def get_relevant(
        self,
        *,
        character_id: str,
        limit: int = 20,
        before: tuple[datetime, str] | None = None,
    ) -> Result[list[CharacterMemory], RepositoryError]:
        """Read memories owned by the character."""
        pass

    @abstractmethod
    async def save(
        self, memories: Sequence[CharacterMemory]
    ) -> Result[None, RepositoryError]:
        """Save memory candidates idempotently by source message and sequence."""
        pass

    @abstractmethod
    async def get_selection_summaries(
        self,
        *,
        character_ids: Sequence[str],
        before: tuple[datetime, str] | None = None,
    ) -> Result[dict[str, CharacterMemorySummary], RepositoryError]:
        """Read compact working memory for the character-selection prompt."""
        pass

    @abstractmethod
    async def save_selection_summary(
        self, summary: CharacterMemorySummary
    ) -> Result[None, RepositoryError]:
        """Save a newer compact working-memory projection for one character."""
        pass
