"""System Instruction aggregate root."""

from dataclasses import dataclass
from typing import Self

from app.core.result import Err, Ok, Result
from app.domain.value_objects.ai_provider import AIProvider
from app.domain.value_objects.system_instruction_id import SystemInstructionId


@dataclass
class SystemInstruction:
    """System Instruction aggregate.

    Represents a system instruction configuration for an AI provider.
    """

    _id: SystemInstructionId
    _provider: AIProvider
    _instruction: str
    _is_active: bool

    @classmethod
    def create(
        cls, provider: AIProvider, instruction: str, is_active: bool = False
    ) -> Result[Self, Exception]:
        """Create a new SystemInstruction.

        Args:
            provider: The AI provider this instruction is for.
            instruction: The actual instruction text.
            is_active: Whether this instruction is currently active.

        Returns:
            Result containing the new SystemInstruction or an error.
        """
        id_result = SystemInstructionId.generate()
        if isinstance(id_result, Err):
            return Err(id_result.error)

        return Ok(
            cls(
                _id=id_result.unwrap(),
                _provider=provider,
                _instruction=instruction,
                _is_active=is_active,
            )
        )

    @classmethod
    def reconstruct(
        cls,
        id: SystemInstructionId,
        provider: AIProvider,
        instruction: str,
        is_active: bool,
    ) -> "SystemInstruction":
        """Reconstruct an existing SystemInstruction from persistence.

        Args:
            id: The existing ID.
            provider: The AI provider.
            instruction: The instruction text.
            is_active: Whether the instruction is active.

        Returns:
            Reconstructed SystemInstruction.
        """
        return cls(
            _id=id,
            _provider=provider,
            _instruction=instruction,
            _is_active=is_active,
        )

    @property
    def id(self) -> SystemInstructionId:
        """Get the ID."""
        return self._id

    @property
    def provider(self) -> AIProvider:
        """Get the provider."""
        return self._provider

    @property
    def instruction(self) -> str:
        """Get the instruction text."""
        return self._instruction

    @property
    def is_active(self) -> bool:
        """Check if this instruction is active."""
        return self._is_active

    def activate(self) -> None:
        """Activate this instruction."""
        self._is_active = True

    def deactivate(self) -> None:
        """Deactivate this instruction."""
        self._is_active = False
