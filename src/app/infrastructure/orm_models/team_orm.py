"""ORM model for Team table."""

from datetime import datetime

from sqlalchemy import Column, DateTime, func
from sqlmodel import Field, SQLModel


class TeamORM(SQLModel, table=True):
    """ORM model for Team table.

    This is the database representation, separate from the domain aggregate.
    Never expose this directly to use cases or domain layer.
    """

    __tablename__ = "teams"  # type: ignore[reportAssignmentType]

    id: str | None = Field(default=None, primary_key=True, max_length=26)
    name: str = Field(max_length=100, index=True)
    version: int = Field(default=0)
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
