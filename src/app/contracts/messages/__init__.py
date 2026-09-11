"""Shared application messages."""

from app.contracts.messages.generated_character_response import (
    CharacterSelection,
    GeneratedCharacterResponse,
)
from app.contracts.messages.speech_message import CharacterSpeechMessage
from app.contracts.messages.times_message import TimesEpisodePlan, TimesPost
from app.contracts.messages.user_events import (
    USER_CREATED_TOPIC,
    UserCreatedEvent,
)

__all__ = [
    "USER_CREATED_TOPIC",
    "CharacterSelection",
    "CharacterSpeechMessage",
    "GeneratedCharacterResponse",
    "TimesEpisodePlan",
    "TimesPost",
    "UserCreatedEvent",
]
