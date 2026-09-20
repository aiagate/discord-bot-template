"""Ordered durable delivery with no automatic retry of ambiguous POSTs."""

from app.contracts.messages.collective import Character, CollectiveSettings
from app.contracts.ports.collective import CollectiveStore, DeliveryResult, Publisher
from app.usecases.collective.lifecycle import refresh_speech


class Delivery:
    """Send only persisted conversational text, independently from work."""

    def __init__(
        self,
        store: CollectiveStore,
        publisher: Publisher,
        characters: dict[str, Character],
        settings: CollectiveSettings,
    ) -> None:
        self.store = store
        self.publisher = publisher
        self.characters = characters
        self.settings = settings

    def recover(self) -> None:
        """A crash during POST cannot establish whether it was delivered."""
        with self.store.transaction() as state:
            for part in state.parts.values():
                if part.status == "sending":
                    part.status = "unknown"
                    part.error = "Delivery interrupted; outcome unknown"
                    state.speeches[part.speech_id].status = "unknown"

    async def step(self, now: float) -> bool:
        """Preserve order per destination and allow unrelated destinations through."""
        with self.store.transaction() as state:
            for speech in state.speeches.values():
                if speech.status != "ready":
                    continue
                activity = state.activities.get(speech.activity_id or "")
                if activity is not None and activity.version != speech.activity_version:
                    refresh_speech(state, speech, now)
                    continue
                if any(p.speech_id == speech.id for p in state.parts.values()):
                    continue
                parts = self.publisher.split(speech)
                if not parts:
                    raise ValueError("Nonempty speech must produce delivery parts")
                for part in parts:
                    state.parts[part.id] = part
            blocked: set[str] = set()
            selected = None
            for part in state.parts.values():
                if part.status == "sent":
                    continue
                if part.destination in blocked:
                    continue
                blocked.add(part.destination)
                if part.status in {"sending", "held"}:
                    continue
                if part.status == "unknown" and part.message_id is None:
                    continue
                if part.next_at > now:
                    continue
                if part.status != "unknown":
                    part.status = "sending"
                    part.attempted_at = now
                    part.attempts += 1
                selected = part.model_copy(deep=True)
                break
        if selected is None:
            return False
        speech = self.store.read().speeches[selected.speech_id]
        try:
            if selected.status == "unknown":
                result = await self.publisher.reconcile(selected)
            else:
                result = await self.publisher.send(
                    selected, self.characters[speech.character_id]
                )
        except Exception:
            result = DeliveryResult(
                "unknown", selected.message_id, "Transport outcome unknown"
            )
        with self.store.transaction() as state:
            part = state.parts[selected.id]
            part.message_id = result.message_id or part.message_id
            part.error = result.error
            part.next_at = now + max(self.settings.retry_seconds, result.retry_after)
            if result.status == "sent" and part.message_id:
                part.status = "sent"
            elif result.status == "rejected":
                part.status = (
                    "held"
                    if part.attempts >= self.settings.max_attempts
                    else "rejected"
                )
            else:
                part.status = "unknown"
            speech = state.speeches[part.speech_id]
            siblings = [p for p in state.parts.values() if p.speech_id == speech.id]
            if all(p.status == "sent" for p in siblings):
                speech.status = "sent"
            elif any(p.status == "unknown" for p in siblings):
                speech.status = "unknown"
            else:
                speech.status = "sending"
        return True

    def confirm(self, part_id: str, message_id: str) -> None:
        """Attach an operator-supplied ID for subsequent API reconciliation."""
        if not message_id.isdecimal():
            raise ValueError("A Discord message ID is required")
        with self.store.transaction() as state:
            part = state.parts[part_id]
            if part.status != "unknown":
                raise ValueError("Only unknown delivery can be reconciled")
            part.message_id = message_id
            part.next_at = 0

    def retry(self, part_id: str) -> None:
        """Retry a definitely rejected delivery only; never resend unknown posts."""
        with self.store.transaction() as state:
            part = state.parts[part_id]
            if part.status not in {"rejected", "held"}:
                raise ValueError("Only a definitely rejected delivery can be retried")
            part.status = "ready"
            part.attempts = 0
            part.next_at = 0
