"""ORM model for TeamMembership table."""

from datetime import datetime

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


class TeamMembershipORM(SQLModel, table=True):
    """ORM model for team_memberships table.

    This is the database representation, separate from the domain aggregate.
    """

    __tablename__ = "team_memberships"  # type: ignore[reportAssignmentType]

    id: str | None = Field(default=None, primary_key=True, max_length=26)
    team_id: str = Field(max_length=26, index=True)
    user_id: str = Field(max_length=26, index=True)
    role: str = Field(max_length=50)
    status: str = Field(max_length=50)
    version: int = Field(default=0)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
