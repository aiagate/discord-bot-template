"""SystemInstruction ORM model."""

from datetime import datetime

from sqlalchemy import Boolean, Column, DateTime, String, func
from sqlmodel import Field, SQLModel


class SystemInstructionORM(SQLModel, table=True):
    """System instruction table ORM model."""

    __tablename__ = "system_instructions"  # type: ignore[reportAssignmentType]

    id: str = Field(primary_key=True)
    provider: str = Field(sa_column=Column(String, nullable=False))
    instruction: str = Field(sa_column=Column(String, nullable=False))
    is_active: bool = Field(sa_column=Column(Boolean, default=False, nullable=False))
    created_at: datetime = Field(
        sa_column=Column(DateTime(timezone=True), server_default=func.now())
    )
    updated_at: datetime = Field(
        sa_column=Column(
            DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
        )
    )
