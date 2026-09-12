"""Application port for generating character responses."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from flow_res import Result

from app.contracts.messages import (
    CharacterSelection,
    GeneratedCharacterResponse,
    TimesPost,
)


class CharacterGenerationErrorType(Enum):
    """Types of character response generation errors."""

    GENERATION_FAILED = auto()
    EMPTY_RESPONSE = auto()
    INVALID_RESPONSE = auto()


@dataclass(frozen=True)
class CharacterGenerationError(Exception):
    """Represents a failure while generating a character response."""

    type: CharacterGenerationErrorType
    message: str

    def __str__(self) -> str:
        """Return the generation error message."""
        return self.message


class ICharacterResponseGenerator(ABC):
    """Generate structured response using a character-specific system instruction."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release resources held by the response generator."""
        pass

    @abstractmethod
    async def select_character(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_names: tuple[str, ...],
    ) -> Result[CharacterSelection, CharacterGenerationError]:
        """Select one registered character for the supplied conversation."""
        pass

    @abstractmethod
    async def generate(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_name: str,
    ) -> Result[GeneratedCharacterResponse, CharacterGenerationError]:
        """Generate a response for the selected character."""
        pass

    @abstractmethod
    async def generate_times_episode(
        self,
        *,
        system_instruction: str,
        user_content: str,
        character_names: tuple[str, ...],
    ) -> Result[tuple[TimesPost, ...], CharacterGenerationError]:
        """Generate zero or more character posts for a Times episode."""
        pass
