"""Persistent delivery progress for Discord Times episodes."""

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime
from sqlmodel import Field, SQLModel


class TimesEpisodeORM(SQLModel, table=True):
    """A Times episode delivery plan, retained to deduplicate repeated triggers."""

    __tablename__ = "times_episodes"  # type: ignore[reportAssignmentType]

    source_message_id: str = Field(primary_key=True, max_length=255)
    guild_id: str = Field(max_length=255)
    channel_id: str = Field(max_length=255, index=True)
    status: str = Field(default="PENDING", max_length=32, index=True)
    next_post_index: int = Field(default=0)
    failure: str | None = Field(default=None, nullable=True)
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
    payload: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
