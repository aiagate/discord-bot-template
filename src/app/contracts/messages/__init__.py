"""Shared application messages."""

from app.contracts.messages.generated_character_response import (
    CharacterSelection,
    GeneratedCharacterResponse,
)
from app.contracts.messages.speech_message import CharacterSpeechMessage
from app.contracts.messages.times_message import TimesEpisodePlan, TimesPost
from app.contracts.messages.user_memory import (
    UserMemoryContext,
    UserMemoryExtractionRequest,
    UserMemoryExtractionResult,
    UserMemoryProfile,
    UserMemoryProfilePatch,
    UserMemorySource,
    UserMemorySourceEvaluation,
    UserMemoryTimelinePatch,
    UserTimelineEntry,
)

__all__ = [
    "CharacterSelection",
    "CharacterSpeechMessage",
    "GeneratedCharacterResponse",
    "TimesEpisodePlan",
    "TimesPost",
    "UserMemoryContext",
    "UserMemoryExtractionRequest",
    "UserMemoryExtractionResult",
    "UserMemoryProfile",
    "UserMemoryProfilePatch",
    "UserMemorySource",
    "UserMemorySourceEvaluation",
    "UserMemoryTimelinePatch",
    "UserTimelineEntry",
]
