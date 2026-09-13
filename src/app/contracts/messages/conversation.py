"""Conversation meaning and work requests, independent of a model provider."""

from typing import Literal

from app.contracts.messages.support import (
    Activity,
    Character,
    Continuity,
    Event,
    Record,
    RuntimeObservation,
    Text,
)


class ConversationContext(Record):
    """Give a speaker identity, original input, shared memory, and current work."""

    message: Event
    character: Character
    master: str
    history: tuple[Event, ...]
    memories: dict[str, str]
    activity: Activity
    continuity: Continuity
    runtime: tuple[RuntimeObservation, ...]


class ConversationDecision(Record):
    """Decide what to say and whether the original input affects ongoing work."""

    action: Literal["reply", "work", "stop", "resume"]
    content: Text
    rationale: Text
