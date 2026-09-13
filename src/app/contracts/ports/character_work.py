"""Boundaries for durable character work and its execution."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from flow_res import Result

from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkAttachment,
    WorkEvent,
)
from app.contracts.messages.speech_message import PublishedSpeech
from app.domain.characters import CharacterDefinition


class ICharacterWorkStore(ABC):
    """Persist task state outside the agent's writable workspace."""

    @abstractmethod
    async def save(self, task: CharacterWork) -> None:
        """Atomically save a task or raise CharacterWorkError."""

    @abstractmethod
    async def list_tasks(self) -> list[CharacterWork]:
        """Read persisted tasks or raise CharacterWorkError."""

    @abstractmethod
    async def recent_reviewed_work(
        self,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        limit: int = 3,
    ) -> list[CharacterWork]:
        """Read recent completed Discord work reviewed for one conversation."""


class ICharacterWorkContextProvider(ABC):
    """Build bounded application context for a Codex work session."""

    @abstractmethod
    async def build(self, task: CharacterWork) -> str:
        """Return untrusted reference context for one task."""
        pass


class ICharacterWorkRequester(ABC):
    """Start or continue work from an ordinary character response."""

    @property
    @abstractmethod
    def enabled(self) -> bool:
        """Return whether the work tool is available to character responses."""
        pass

    @abstractmethod
    def current(
        self, guild_id: str, channel_id: str, owner_id: str
    ) -> CharacterWork | None:
        """Return the latest linked work in one owner's conversation."""
        pass

    @abstractmethod
    def can_submit(
        self,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        *,
        authorization_channel_id: str | None = None,
    ) -> bool:
        """Return whether this Discord scope may invoke the work tool."""
        pass

    @abstractmethod
    async def submit(
        self,
        *,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        message_id: str,
        character_id: str,
        prompt: str,
        authorization_channel_id: str | None = None,
    ) -> Result[CharacterWork, CharacterWorkError]:
        """Start new work or steer the linked work for one conversation."""
        pass


class ICharacterWorkExecutor(ABC):
    """Run and control work without depending on a particular agent SDK."""

    @abstractmethod
    def run(self, task: CharacterWork, instructions: str) -> AsyncGenerator[WorkEvent]:
        """Yield session identity, progress, and a terminal event."""

    @abstractmethod
    async def steer(self, task_id: str, prompt: str) -> bool:
        """Deliver extra input to a live turn; return false if it has ended."""

    @abstractmethod
    async def attachments(self, task: CharacterWork) -> tuple[WorkAttachment, ...]:
        """Read and verify the stored result without rerunning the task."""


class ICharacterWorkReporter(ABC):
    """Publish work in the character's identity and confirm the destination."""

    @abstractmethod
    async def send(
        self,
        task: CharacterWork,
        character: CharacterDefinition,
        text: str,
        attachments: tuple[WorkAttachment, ...],
    ) -> PublishedSpeech:
        """Send a report and files, or raise CharacterWorkError."""
