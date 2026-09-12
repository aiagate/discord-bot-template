"""Ports for user memory storage, source selection, and extraction."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import datetime

from flow_res import Result

from app.contracts.messages.user_memory import (
    UserMemoryContext,
    UserMemoryExtractionRequest,
    UserMemoryExtractionResult,
    UserMemoryProfilePatch,
    UserMemorySource,
    UserMemoryTimelinePatch,
)
from app.domain.repositories import RepositoryError


@dataclass(frozen=True)
class MemoryExtractionError(Exception):
    """Failure returned by an external semantic memory extractor."""

    message: str

    def __str__(self) -> str:
        """Return a safe diagnostic message."""
        return self.message


class IUserMemoryStore(ABC):
    """Read and atomically project user-owned Markdown memory."""

    @abstractmethod
    async def get_context(
        self, user_id: str, *, limit: int = 20
    ) -> Result[UserMemoryContext, RepositoryError]:
        """Read one bounded user's Profile and Timeline context."""
        pass

    @abstractmethod
    async def apply(
        self,
        *,
        user_id: str,
        profile_patch: UserMemoryProfilePatch | None,
        timeline_patches: tuple[UserMemoryTimelinePatch, ...],
        source_messages: tuple[UserMemorySource, ...],
        reference_time: datetime,
        day: str,
    ) -> Result[None, RepositoryError]:
        """Apply validated changes owned by one canonical user."""
        pass


class IUserMemorySourceStore(ABC):
    """Select unprocessed raw chat and record successful consolidation."""

    @abstractmethod
    async def list_pending(
        self, *, reference_time: datetime, limit: int = 500
    ) -> Result[list[UserMemorySource], RepositoryError]:
        """Return eligible user-owned raw messages before the current JST day."""
        pass

    @abstractmethod
    async def mark_processed(
        self, message_ids: tuple[str, ...], *, processed_at: datetime
    ) -> Result[None, RepositoryError]:
        """Mark successfully evaluated sources so a retry is idempotent."""
        pass


class IUserMemoryExtractor(ABC):
    """Extract conservative Profile and Timeline patches from raw chat."""

    @abstractmethod
    async def extract(
        self, request: UserMemoryExtractionRequest
    ) -> Result[UserMemoryExtractionResult, MemoryExtractionError]:
        """Return a strict, source-referencing extraction result."""
        pass

    @abstractmethod
    async def aclose(self) -> None:
        """Release resources held by the extractor."""
        pass
