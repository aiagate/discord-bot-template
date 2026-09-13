"""Persistent delivery progress for single-process character responses."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class SpeechDeliveryORM(SQLModel, table=True):
    """A response plan, retained to deduplicate repeated source messages."""

    __tablename__ = "speech_deliveries"  # type: ignore[reportAssignmentType]

    source_message_id: str = Field(primary_key=True, max_length=255)
    guild_id: str = Field(max_length=255)
    channel_id: str = Field(max_length=255, index=True)
    finished: bool = False
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
