from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.aggregates.command import Command
from app.domain.repositories.command_repository import ICommandRepository
from app.infrastructure.orm_models.command_outbox_orm import CommandOutboxORM


class SQLAlchemyCommandRepository(ICommandRepository):
    """SQLAlchemy implementation of command repository."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def dequeue(self) -> Command | None:
        """Dequeue the next pending command."""
        stmt = (
            select(CommandOutboxORM)
            .where(CommandOutboxORM.status == "PENDING")  # pyright: ignore
            .order_by(CommandOutboxORM.created_at)  # pyright: ignore
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if not orm:
            return None

        # Map ORM to domain
        return Command(
            id=orm.id,
            type=orm.command_type,
            payload=orm.payload,
            created_at=orm.created_at or datetime.now(UTC),
            status=orm.status,
            processed_at=orm.processed_at,
        )

    async def complete(self, command_id: UUID) -> None:
        """Mark command as processed."""
        stmt = select(CommandOutboxORM).where(CommandOutboxORM.id == command_id)  # pyright: ignore
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = "PROCESSED"
            orm.processed_at = datetime.now(UTC)

    async def fail(self, command_id: UUID) -> None:
        """Mark command as failed."""
        stmt = select(CommandOutboxORM).where(CommandOutboxORM.id == command_id)  # pyright: ignore
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = "FAILED"
