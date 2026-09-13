"""Only the boundaries that need interchangeable implementations."""

from collections.abc import Awaitable, Callable
from typing import Protocol

from app.contracts.messages.support import (
    Activity,
    Character,
    Context,
    DeliveryReceipt,
    Notice,
    Outcome,
    RuntimeObservation,
)

EvidenceWriter = Callable[[str, str], Awaitable[None]]


class Thinker(Protocol):
    """Observe, act, and decide how a support activity should proceed."""

    async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
        """Return a decision while recording observable execution evidence."""
        ...


class Speaker(Protocol):
    """Express content without changing the underlying activity."""

    async def render(self, notice: Notice, character: Character) -> str:
        """Return only a character's human-readable expression."""
        ...


class Publisher(Protocol):
    """Deliver saved content using its stable notification identity."""

    async def send(
        self, notice: Notice, character: Character
    ) -> DeliveryReceipt | None:
        """Deliver one notice; retries may reuse its ID."""
        ...


class SupportStore(Protocol):
    """Own atomic lifecycle transitions and immutable evidence."""

    def observe(self, observation: RuntimeObservation) -> None:
        """Record runtime facts without changing the activity revision."""
        ...

    def claim(self, now: float) -> Activity | None:
        """Claim one due activity, consuming one execution from its budget."""
        ...

    def current(self, activity_id: str) -> Activity:
        """Return a fresh state for stop and correction detection."""
        ...

    def context(self, activity: Activity, now: float) -> Context:
        """Provide authoritative policy and paths to all durable evidence."""
        ...

    def record(self, activity: Activity, kind: str, content: str, now: float) -> None:
        """Append observed evidence, even when the activity was interrupted."""
        ...

    def finish(self, activity: Activity, outcome: Outcome, now: float) -> bool:
        """Commit a decision only if no newer user action superseded it."""
        ...

    def fail(self, activity: Activity, reason: str, now: float) -> None:
        """Record failure and schedule a bounded retry without claiming success."""
        ...

    def pending_notices(self) -> tuple[Notice, ...]:
        """Read undelivered notices in creation order."""
        ...

    def save_rendered(self, notice_id: str, content: str) -> None:
        """Preserve the same wording across delivery retries."""
        ...

    def delivered(self, notice_id: str, receipt: DeliveryReceipt | None = None) -> None:
        """Mark successful delivery without changing work state."""
        ...

    def character(self, character_id: str) -> Character:
        """Read a character's portable definition."""
        ...
