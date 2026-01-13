from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class EventQueueORM(SQLModel, table=True):
    """Event Queue table for storing incoming events."""

    __tablename__ = "event_queue"  # type: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    type: str = Field(sa_column=Column(String, nullable=False))
    payload: dict[str, Any] = Field(default={}, sa_column=Column(JSONB, nullable=False))
    status: str = Field(
        default="PENDING", sa_column=Column(String, nullable=False, index=True)
    )
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    processed_at: datetime | None = Field(
        default=None, sa_column=Column(DateTime(timezone=True), nullable=True)
    )
