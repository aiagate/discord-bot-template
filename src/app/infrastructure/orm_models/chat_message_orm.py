"""SQLModel representation of persisted chat messages."""

from datetime import datetime
from typing import Any

from sqlalchemy import JSON, Column, DateTime, ForeignKey, Index, String
from sqlmodel import Field, SQLModel


class ChatMessageORM(SQLModel, table=True):
    """Database row for one immutable chat message."""

    __tablename__ = "chat_messages"  # type: ignore[reportAssignmentType]
    __table_args__ = (
        Index(
            "uq_chat_messages_external_id",
            "platform",
            "external_message_id",
            unique=True,
        ),
    )

    id: str = Field(primary_key=True, max_length=26)
    platform: str = Field(sa_column=Column(String(20), nullable=False, index=True))
    conversation_scope: dict[str, str] = Field(sa_column=Column(JSON, nullable=False))
    external_sender_id: str = Field(
        sa_column=Column(String(255), nullable=False, index=True)
    )
    author_kind: str = Field(sa_column=Column(String(32), nullable=False, index=True))
    content: dict[str, Any] = Field(sa_column=Column(JSON, nullable=False))
    occurred_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), nullable=False, index=True)
    )
    user_id: str | None = Field(
        default=None,
        sa_column=Column(String(26), ForeignKey("users.id"), nullable=True, index=True),
    )
    external_message_id: str | None = Field(default=None, max_length=255)
    author_name: str | None = Field(default=None, max_length=255)
    reply_to_external_message_id: str | None = Field(default=None, max_length=255)
