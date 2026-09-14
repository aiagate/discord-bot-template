"""Application port for replaceable character response providers."""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum, auto

from flow_res import Result

from app.contracts.messages.character_prompt import (
    CharacterConversationContext,
    CharacterSelectionContext,
)
from app.contracts.messages.generated_character_response import (
    CharacterSelection,
    GeneratedCharacterResponse,
)


class CharacterGenerationErrorType(Enum):
    """Types of character response generation errors."""

    GENERATION_FAILED = auto()
    EMPTY_RESPONSE = auto()
    INVALID_RESPONSE = auto()


@dataclass(frozen=True, slots=True)
class CharacterGenerationError(Exception):
    """Represents a failure while generating a character response."""

    type: CharacterGenerationErrorType
    message: str

    def __str__(self) -> str:
        """Return the generation error message."""
        return self.message


class ICharacterResponseGenerator(ABC):
    """Generate responses through a provider independent of application use cases."""

    @abstractmethod
    async def aclose(self) -> None:
        """Release resources held by the response generator."""
        pass

    @abstractmethod
    async def select_character(
        self, context: CharacterSelectionContext
    ) -> Result[CharacterSelection, CharacterGenerationError]:
        """Select one registered character for the supplied conversation."""
        pass

    @abstractmethod
    async def generate(
        self, context: CharacterConversationContext
    ) -> Result[GeneratedCharacterResponse, CharacterGenerationError]:
        """Generate one response for the selected character."""
        pass
