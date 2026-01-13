from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.events import AppEvent, EventType
from app.infrastructure.orm_models.command_outbox_orm import CommandOutboxORM
from app.infrastructure.orm_models.event_queue_orm import EventQueueORM


class QueueRepository:
    """Repository for Event Queue and Command Outbox."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def enqueue_event(self, event: AppEvent) -> None:
        """Enqueue an event."""
        orm = EventQueueORM(type=event.type.name, payload=event.payload)
        self._session.add(orm)

    async def dequeue_event(self) -> tuple[UUID, AppEvent] | None:
        """Dequeue the next pending event.

        Simplistic implementation without SKIP LOCKED for MVP compatibility with SQLite if needed,
        though designed for Postgres.
        """
        # Lock rows in Postgres to avoid race conditions: with_for_update(skip_locked=True)
        # Note: SQLite doesn't support skip_locked.
        # Assuming Postgres as per requirements.
        stmt = (
            select(EventQueueORM)
            .where(EventQueueORM.status == "PENDING")  # pyright: ignore[reportArgumentType]
            .order_by(EventQueueORM.created_at)  # pyright: ignore[reportArgumentType]
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()

        if not orm:
            return None

        orm.status = "PROCESSING"
        # We don't commit here; caller should commit after processing or marking complete.
        # But for 'dequeue' semantics usually we return and let caller handle transaction scope.
        # Here we just return the object attached to session.

        # Convert to domain
        try:
            event_type = EventType[orm.type]
        except KeyError:
            # Unknown event type, fail it
            orm.status = "FAILED"
            return None

        event = AppEvent(
            type=event_type,
            payload=orm.payload,
            timestamp=orm.created_at
            or datetime.now(UTC),  # Use creation time as timestamp
        )
        return (orm.id, event)

    async def complete_event(self, event_id: UUID) -> None:
        """Mark event as processed."""
        stmt = select(EventQueueORM).where(EventQueueORM.id == event_id)  # pyright: ignore[reportArgumentType]
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = "PROCESSED"
            orm.processed_at = datetime.now(UTC)

    async def fail_event(self, event_id: UUID) -> None:
        """Mark event as failed."""
        stmt = select(EventQueueORM).where(EventQueueORM.id == event_id)  # pyright: ignore[reportArgumentType]
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = "FAILED"

    # --- Command Outbox methods ---

    async def enqueue_command(self, command_type: str, payload: dict[str, Any]) -> None:
        """Enqueue a command for the bot."""
        orm = CommandOutboxORM(command_type=command_type, payload=payload)
        self._session.add(orm)

    async def dequeue_command(self) -> CommandOutboxORM | None:
        """Dequeue next pending command."""
        stmt = (
            select(CommandOutboxORM)
            .where(CommandOutboxORM.status == "PENDING")  # pyright: ignore[reportArgumentType]
            .order_by(CommandOutboxORM.created_at)  # pyright: ignore[reportArgumentType]
            .limit(1)
            .with_for_update(skip_locked=True)
        )
        result = await self._session.execute(stmt)
        return result.scalar_one_or_none()

    async def complete_command(self, command_id: UUID) -> None:
        """Mark command as processed."""
        stmt = select(CommandOutboxORM).where(CommandOutboxORM.id == command_id)  # pyright: ignore[reportArgumentType]
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = "PROCESSED"
            orm.processed_at = datetime.now(UTC)

    async def fail_command(self, command_id: UUID) -> None:
        """Mark command as failed."""
        stmt = select(CommandOutboxORM).where(CommandOutboxORM.id == command_id)  # pyright: ignore[reportArgumentType]
        result = await self._session.execute(stmt)
        orm = result.scalar_one_or_none()
        if orm:
            orm.status = "FAILED"
