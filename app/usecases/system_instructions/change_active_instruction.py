"""Use case to change active system instruction."""

from dataclasses import dataclass

from app.core.result import Err, Ok, Result
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.repositories import IUnitOfWork
from app.domain.repositories.interfaces import RepositoryError, RepositoryErrorType
from app.domain.value_objects.system_instruction_id import SystemInstructionId


@dataclass(frozen=True)
class ChangeActiveSystemInstruction:
    """Use case to change the active system instruction."""

    uow: IUnitOfWork

    async def execute(
        self, instruction_id: SystemInstructionId
    ) -> Result[None, Exception]:
        """Execute the use case.

        Args:
            instruction_id: The ID of the instruction to activate.

        Returns:
            Success or failure.
        """
        async with self.uow:
            repo = self.uow.GetRepository(SystemInstruction)

            # Find the instruction to activate
            target_result = await repo.find_by_id(instruction_id)
            if isinstance(target_result, Err):
                return Err(target_result.error)

            target_instruction = target_result.unwrap()
            if not target_instruction:
                return Err(
                    RepositoryError(
                        RepositoryErrorType.NOT_FOUND,
                        f"Instruction {instruction_id} not found",
                    )
                )

            # Find currently active instruction for this provider
            active_result = await repo.find_active_by_provider(
                target_instruction.provider
            )
            if isinstance(active_result, Err):
                # If unexpected error, abort
                return Err(active_result.error)

            # Deactivate currently active one if exists and different
            active_instruction = active_result.unwrap()
            if active_instruction and active_instruction.id != target_instruction.id:
                active_instruction.deactivate()
                save_result = await repo.save(active_instruction)
                if isinstance(save_result, Err):
                    return Err(save_result.error)

            # Activate target
            if not target_instruction.is_active:
                target_instruction.activate()
                save_result = await repo.save(target_instruction)
                if isinstance(save_result, Err):
                    return Err(save_result.error)

            await self.uow.commit()

        return Ok(None)
