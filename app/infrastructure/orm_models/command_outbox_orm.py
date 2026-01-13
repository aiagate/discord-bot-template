from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import Column, DateTime, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlmodel import Field, SQLModel


class CommandOutboxORM(SQLModel, table=True):
    """Command Outbox table for storing commands to the bot."""

    __tablename__ = "command_outbox"  # type: ignore[reportAssignmentType]

    id: UUID = Field(default_factory=uuid4, primary_key=True)
    command_type: str = Field(sa_column=Column(String, nullable=False))
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
