"""External boundaries used by collective use cases."""

from collections.abc import Awaitable, Callable
from contextlib import AbstractContextManager
from typing import Protocol

from app.contracts.messages.collective import (
    Character,
    CharacterContext,
    CollectiveState,
    Decision,
    ModelLimits,
    Speech,
    SpeechPart,
    WorkContext,
    WorkResult,
)

ExecutionRecorder = Callable[[str, str], Awaitable[None]]


class CollectiveStore(Protocol):
    """Commit related updates together without awaiting external calls."""

    def transaction(self) -> AbstractContextManager[CollectiveState]:
        """Load a current snapshot and atomically persist successful changes."""
        ...

    def read(self) -> CollectiveState:
        """Read a consistent snapshot."""
        ...


class Conversation(Protocol):
    """Replaceable conversational ability of the selected character."""

    async def limits(self) -> ModelLimits:
        """Fetch current model limits."""
        ...

    async def count(self, context: CharacterContext, speech: Speech | None) -> int:
        """Count the complete request including instructions and output schema."""
        ...

    async def converse(self, context: CharacterContext) -> Decision:
        """Speak and decide as the selected person."""
        ...

    async def render(self, context: CharacterContext, speech: Speech) -> str:
        """Express the committed facts in the person's natural voice."""
        ...


class CodexWork(Protocol):
    """Codex-specific execution, interruption, and orphan recovery."""

    async def run_codex(
        self, context: WorkContext, record: ExecutionRecorder
    ) -> WorkResult:
        """Run one tracked App Server turn."""
        ...

    async def interrupt(self, run_id: str) -> bool:
        """Return true only after the run and its child processes have exited."""
        ...

    async def recover(self, execution: dict[str, str]) -> bool:
        """Confirm the previous process tree has exited."""
        ...

    def saved_result(self, execution: dict[str, str]) -> str | None:
        """Read a durably saved result that did not yet reach the application DB."""
        ...


class Workspaces(Protocol):
    """Project confirmed state before starting another run."""

    def prepare(self, context: WorkContext, state: CollectiveState) -> WorkContext:
        """Validate guides and project the input snapshot atomically per file."""
        ...


class DeliveryResult:
    """One delivery attempt or reconciliation result."""

    def __init__(
        self,
        status: str,
        message_id: str | None = None,
        error: str = "",
        retry_after: float = 0,
    ) -> None:
        self.status = status
        self.message_id = message_id
        self.error = error
        self.retry_after = retry_after


class Publisher(Protocol):
    """Transport cannot create speech or mutate durable application state."""

    def split(self, speech: Speech) -> list[SpeechPart]:
        """Return fixed payloads with a configured destination."""
        ...

    async def send(self, part: SpeechPart, character: Character) -> DeliveryResult:
        """Perform exactly one POST; do not retry ambiguous sends."""
        ...

    async def reconcile(self, part: SpeechPart) -> DeliveryResult:
        """Check a known message ID without inferring non-delivery from absence."""
        ...


class InputTooLarge(Exception):
    """The provider rejected input capacity, not a transport failure."""


class HoldTurn(Exception):
    """The saved input needs an operator or changed conditions before retrying."""
