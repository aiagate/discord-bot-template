"""Processed raw-chat markers for long-term memory consolidation."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime
from sqlmodel import Field, SQLModel


class MemoryConsolidatedChatSourceORM(SQLModel, table=True):
    """Record that one raw chat source was evaluated successfully."""

    __tablename__ = "memory_consolidated_chat_sources"  # type: ignore[reportAssignmentType]

    chat_message_id: str = Field(
        primary_key=True,
        foreign_key="chat_messages.id",
        max_length=26,
    )
    consolidated_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
