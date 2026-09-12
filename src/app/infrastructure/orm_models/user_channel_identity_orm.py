"""Provider identity mapping for canonical users."""

from datetime import UTC, datetime

from sqlalchemy import Column, DateTime, ForeignKey, String
from sqlmodel import Field, SQLModel


class UserChannelIdentityORM(SQLModel, table=True):
    """Map one provider participant identity to a canonical User."""

    __tablename__ = "user_channel_identities"  # type: ignore[reportAssignmentType]

    platform: str = Field(primary_key=True, max_length=20)
    external_participant_id: str = Field(primary_key=True, max_length=255)
    user_id: str = Field(
        sa_column=Column(String(26), ForeignKey("users.id"), nullable=False, index=True)
    )
    created_at: datetime = Field(
        default_factory=lambda: datetime.now(UTC),
        sa_column=Column(DateTime(timezone=True), nullable=False),
    )
