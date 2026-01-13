"""Repository interface for SystemInstruction."""

from abc import ABC, abstractmethod

from app.core.result import Result
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.value_objects.ai_provider import AIProvider
from app.domain.value_objects.system_instruction_id import SystemInstructionId


class ISystemInstructionRepository(ABC):
    """Interface for System Instruction repository."""

    @abstractmethod
    async def save(self, instruction: SystemInstruction) -> Result[None, Exception]:
        """Save a system instruction.

        Args:
            instruction: The instruction to save.
        """
        ...

    @abstractmethod
    async def find_by_id(
        self, id: SystemInstructionId
    ) -> Result[SystemInstruction | None, Exception]:
        """Find a system instruction by ID.

        Args:
            id: The ID to search for.
        """
        ...

    @abstractmethod
    async def find_active_by_provider(
        self, provider: AIProvider
    ) -> Result[SystemInstruction | None, Exception]:
        """Find the currently active instruction for a provider.

        Args:
            provider: The AI provider.
        """
        ...

    @abstractmethod
    async def find_all_by_provider(
        self, provider: AIProvider
    ) -> Result[list[SystemInstruction], Exception]:
        """Find all instructions for a provider.

        Args:
            provider: The AI provider.
        """
        ...
