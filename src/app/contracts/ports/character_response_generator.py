"""Application port for generating character responses."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from enum import Enum, auto

from flow_res import Result

from app.contracts.messages import (
    CharacterSelection,
    CharacterWorkRequest,
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


CharacterWorkTool = Callable[[CharacterWorkRequest], Awaitable[str]]


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
        work_tool: CharacterWorkTool | None = None,
        work_character_names: tuple[str, ...] = (),
    ) -> Result[GeneratedCharacterResponse, CharacterGenerationError]:
        """Generate a response and optionally execute one work tool call."""
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
