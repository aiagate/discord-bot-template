from datetime import datetime

from sqlalchemy import Column, DateTime, String, func
from sqlmodel import Field, SQLModel


class ChatMessageORM(SQLModel, table=True):
    """Chat message table ORM model."""

    __tablename__ = "chat_messages"  # type: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    role: str = Field(sa_column=Column(String, nullable=False))
    content: str = Field(sa_column=Column(String, nullable=False))
    sent_at: datetime = Field(sa_column=Column(DateTime(timezone=True), nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
