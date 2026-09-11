"""Boundaries for durable character work and its execution."""

from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator

from app.contracts.messages.character_work import (
    CharacterWork,
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
