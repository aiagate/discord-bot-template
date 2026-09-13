"""Boundaries for replaceable conversation reasoning and durable input."""

from typing import Protocol

from app.contracts.messages.conversation import (
    ConversationContext,
    ConversationDecision,
)
from app.contracts.messages.support import Event, RuntimeObservation


class ConversationThinker(Protocol):
    """Understand a conversation without executing the requested work."""

    async def think(self, context: ConversationContext) -> ConversationDecision:
        """Return content and an explicit request to the execution runtime."""
        ...

    async def close(self) -> None:
        """Release resources owned by the selected adapter."""
        ...


class ConversationStore(Protocol):
    """Preserve dialogue independently of the activity execution lifecycle."""

    def observe(self, observation: RuntimeObservation) -> None:
        """Record the outcome of a conversation attempt."""
        ...

    def pending_conversation(self) -> Event | None:
        """Read the earliest input that has not received a decision."""
        ...

    def conversation_context(self, message: Event) -> ConversationContext:
        """Read shared identity, memory, dialogue, and a current activity snapshot."""
        ...

    def finish_conversation(
        self, context: ConversationContext, decision: ConversationDecision
    ) -> bool:
        """Commit dialogue and its request once, preserving newer controls."""
        ...
