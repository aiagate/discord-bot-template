"""ORM model for User table."""

from datetime import datetime

from sqlalchemy import Column, DateTime, Integer, func
from sqlmodel import Field, SQLModel

_version_column = Column("version", Integer, nullable=False, default=0)


class UserORM(SQLModel, table=True):
    """ORM model for User table.

    This is the database representation, separate from the domain aggregate.
    Never expose this directly to use cases or domain layer.
    """

    __tablename__ = "users"  # type: ignore[reportAssignmentType]

    id: str | None = Field(default=None, primary_key=True, max_length=26)
    display_name: str = Field(max_length=255, index=True)
    email: str = Field(max_length=255, unique=True, index=True)
    version: int = Field(default=0, sa_column=_version_column)

    __mapper_args__ = {
        "version_id_col": _version_column,
        "version_id_generator": False,
    }
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
