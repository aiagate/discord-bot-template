"""Isolated parent/child persistence model used by repository integration tests."""

from abc import abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime

from flow_res import Err, Ok, Result
from sqlalchemy import CheckConstraint, Column, DateTime, Integer, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import registry
from sqlmodel import Field, Relationship, SQLModel

from app.domain.repositories import (
    IRepositoryWithId,
    RepositoryError,
    RepositoryErrorType,
)
from app.domain.value_objects import Version
from app.infrastructure.repositories.generic_repository import GenericRepository


@dataclass(frozen=True)
class OrderLine:
    id: str
    quantity: int


@dataclass(frozen=True)
class Order:
    id: str
    lines: tuple[OrderLine, ...]
    version: Version = field(default_factory=lambda: Version(0))
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    updated_at: datetime = field(default_factory=lambda: datetime.now(UTC))


class PersistenceModel(SQLModel, registry=registry()):
    pass


class OrderLineORM(PersistenceModel, table=True):
    __tablename__ = "test_order_lines"  # type: ignore[reportAssignmentType]
    __table_args__ = (CheckConstraint("quantity > 0"),)

    id: str = Field(primary_key=True)
    order_id: str = Field(foreign_key="test_orders.id")
    quantity: int


_version_column = Column("version", Integer, nullable=False, default=0)


class OrderORM(PersistenceModel, table=True):
    __tablename__ = "test_orders"  # type: ignore[reportAssignmentType]
    __mapper_args__ = {
        "version_id_col": _version_column,
        "version_id_generator": False,
    }

    id: str = Field(primary_key=True)
    version: int = Field(default=0, sa_column=_version_column)
    created_at: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    updated_at: datetime = Field(sa_column=Column(DateTime(timezone=True)))
    lines: list[OrderLineORM] = Relationship(
        sa_relationship_kwargs={
            "cascade": "all, delete-orphan",
            "lazy": "selectin",
            "order_by": OrderLineORM.id,
        }
    )


def order_to_orm(order: Order) -> SQLModel:
    return OrderORM(
        id=order.id,
        version=order.version.to_primitive(),
        created_at=order.created_at,
        updated_at=order.updated_at,
        lines=[
            OrderLineORM(id=line.id, order_id=order.id, quantity=line.quantity)
            for line in order.lines
        ],
    )


def order_from_orm(row: SQLModel) -> Order:
    assert isinstance(row, OrderORM)
    return Order(
        id=row.id,
        version=Version(row.version),
        created_at=row.created_at,
        updated_at=row.updated_at,
        lines=tuple(OrderLine(line.id, line.quantity) for line in row.lines),
    )


class IOrderRepository(IRepositoryWithId[Order, str]):
    @abstractmethod
    async def count(self) -> int:
        pass

    @abstractmethod
    async def add_with_direct_flush(
        self, order: Order
    ) -> Result[None, RepositoryError]:
        pass


class OrderRepository(GenericRepository[Order, str], IOrderRepository):
    def __init__(self, session: AsyncSession) -> None:
        super().__init__(session, Order, str)

    async def count(self) -> int:
        return (
            await self._session.execute(select(func.count()).select_from(OrderORM))
        ).scalar_one()

    async def add_with_direct_flush(
        self, order: Order
    ) -> Result[None, RepositoryError]:
        try:
            self._session.add(order_to_orm(order))
            await self._session.flush()
            return Ok(None)
        except SQLAlchemyError as error:
            await self._session.rollback()
            return Err(RepositoryError(RepositoryErrorType.UNEXPECTED, str(error)))
