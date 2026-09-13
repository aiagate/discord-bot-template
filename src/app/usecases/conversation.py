"""Advance dialogue without waiting for or restarting autonomous work."""

import time

from app.contracts.messages.support import RuntimeObservation
from app.contracts.ports.conversation import ConversationStore, ConversationThinker


class ConversationRunner:
    """Keep model choice outside conversation behavior and persistence."""

    def __init__(self, store: ConversationStore, thinker: ConversationThinker) -> None:
        self.store = store
        self.thinker = thinker

    async def tick(self) -> bool:
        """Process one durable input; failures leave it available for retry."""
        message = self.store.pending_conversation()
        if message is None:
            return False
        context = self.store.conversation_context(message)
        try:
            decision = await self.thinker.think(context)
        except Exception:
            self.store.observe(
                RuntimeObservation(
                    component="conversation",
                    status="failure",
                    observed_at=time.time(),
                    source=f"input:{message.id}",
                )
            )
            raise
        self.store.observe(
            RuntimeObservation(
                component="conversation",
                status="success",
                observed_at=time.time(),
                source=f"input:{message.id}",
            )
        )
        self.store.finish_conversation(context, decision)
        return True
