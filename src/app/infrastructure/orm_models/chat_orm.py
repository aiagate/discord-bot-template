"""ORM models for Chat with Table Per Hierarchy (TPH) inheritance."""

from datetime import datetime
from typing import Any, ClassVar

from sqlalchemy import JSON, Column, DateTime, String, func
from sqlmodel import Field, SQLModel


class ChatORM(SQLModel, table=True):
    """Base ORM model for Chat using Table Per Hierarchy (TPH).

    This is the database representation using single-table inheritance pattern.
    The 'type' column is the discriminator that determines which concrete class
    (DiscordChatORM or LineChatORM) an instance represents.

    Never expose this directly to use cases or domain layer.
    """

    __tablename__ = "chats"  # type: ignore[reportAssignmentType]

    id: str | None = Field(default=None, primary_key=True, max_length=26)
    type: str = Field(
        sa_column=Column(String(20), nullable=False, index=True)
    )  # Discriminator for polymorphic identity
    user_id: str | None = Field(
        default=None,
        max_length=255,
        sa_column=Column(String(255), nullable=True, index=True),
    )
    role: str | None = Field(
        default=None,
        max_length=32,
        sa_column=Column(String(32), nullable=True, index=True),
    )
    message_content: dict[str, Any] = Field(
        sa_column=Column(JSON, nullable=False),
    )
    version: int = Field(default=0)
    created_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )
    updated_at: datetime | None = Field(
        default=None,
        sa_column=Column(DateTime(timezone=True), server_default=func.now()),
    )

    # Discord-specific fields (nullable for LINE chats)
    discord_guild_id: str | None = Field(default=None, max_length=255)
    discord_channel_id: str | None = Field(default=None, max_length=255)

    # LINE-specific fields (nullable for Discord chats)
    line_user_id: str | None = Field(default=None, max_length=255)
    line_group_id: str | None = Field(default=None, max_length=255)
    line_room_id: str | None = Field(default=None, max_length=255)

    __mapper_args__: ClassVar[dict[str, object]] = {}


DiscordChatORM = ChatORM
LineChatORM = ChatORM
