"""SQLAlchemy implementation of SystemInstructionRepository."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.result import Err, Ok, Result
from app.domain.aggregates.system_instruction import SystemInstruction
from app.domain.repositories.interfaces import RepositoryError, RepositoryErrorType
from app.domain.repositories.system_instruction_repository import (
    ISystemInstructionRepository,
)
from app.domain.value_objects.ai_provider import AIProvider
from app.domain.value_objects.system_instruction_id import SystemInstructionId
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.orm_models.system_instruction_orm import SystemInstructionORM


class SqlAlchemySystemInstructionRepository(ISystemInstructionRepository):
    """SQLAlchemy implementation of System Instruction repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save(self, instruction: SystemInstruction) -> Result[None, Exception]:
        """Save a system instruction."""
        try:
            orm_model = ORMMappingRegistry.to_orm(instruction)
            if not isinstance(orm_model, SystemInstructionORM):
                return Err(
                    RepositoryError(
                        RepositoryErrorType.UNEXPECTED, "Invalid ORM mapping"
                    )
                )

            # Check if it already exists (merge) or just add.
            # Usually merge is safer but for entities with fixed IDs we can check.
            # Simpler to just merge.
            await self._session.merge(orm_model)
            return Ok(None)
        except Exception as e:
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(e)))

    async def find_by_id(
        self, id: SystemInstructionId
    ) -> Result[SystemInstruction | None, Exception]:
        """Find a system instruction by ID."""
        try:
            result = await self._session.get(SystemInstructionORM, id.to_primitive())
            if not result:
                return Ok(None)

            return Ok(ORMMappingRegistry.from_orm(result))
        except Exception as e:
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(e)))

    async def find_active_by_provider(
        self, provider: AIProvider
    ) -> Result[SystemInstruction | None, Exception]:
        """Find the currently active instruction for a provider."""
        try:
            stmt = select(SystemInstructionORM).where(
                SystemInstructionORM.provider == provider.value,  # pyright: ignore[reportArgumentType]
                SystemInstructionORM.is_active.is_(True),  # type: ignore
            )
            result = await self._session.execute(stmt)
            orm_inst = result.scalars().first()

            if not orm_inst:
                return Ok(None)

            return Ok(ORMMappingRegistry.from_orm(orm_inst))
        except Exception as e:
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(e)))

    async def find_all_by_provider(
        self, provider: AIProvider
    ) -> Result[list[SystemInstruction], Exception]:
        """Find all instructions for a provider."""
        try:
            stmt = select(SystemInstructionORM).where(
                SystemInstructionORM.provider == provider.value  # pyright: ignore[reportArgumentType]
            )
            result = await self._session.execute(stmt)
            orm_insts = result.scalars().all()

            return Ok([ORMMappingRegistry.from_orm(orm) for orm in orm_insts])
        except Exception as e:
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(e)))
