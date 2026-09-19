"""Tests for GenericRepository error cases to improve coverage."""

from dataclasses import dataclass
from unittest.mock import patch

import pytest
from flow_res import is_err, is_ok
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.ports import IUnitOfWork
from app.domain.aggregates.user import User
from app.domain.interfaces import IAuditable
from app.domain.repositories import RepositoryErrorType
from app.domain.value_objects import (
    DisplayName,
    Email,
    UserId,
)
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.repositories.generic_repository import GenericRepository


@pytest.mark.anyio
async def test_generic_repository_no_orm_mapping_raises_error(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Test that GenericRepository raises ValueError when ORM mapping not found."""

    @dataclass
    class UnmappedEntity:
        """Dummy entity with no ORM mapping."""

        id: int
        name: str

    # Create a session
    async with session_factory() as session:
        # Try to create repository for unmapped entity
        with pytest.raises(ValueError, match="No ORM mapping found"):
            GenericRepository(session, UnmappedEntity, int)


@pytest.mark.anyio
async def test_generic_repository_get_by_id_sqlalchemy_error(
    uow: IUnitOfWork,
) -> None:
    """Test that get_by_id returns RepositoryError on SQLAlchemy error."""
    user_id = UserId.generate().expect("UserId.generate should succeed")

    async with uow:
        repo = uow.GetRepository(User, UserId)

        # Mock session.execute to raise SQLAlchemyError
        with patch.object(
            repo._session,  # type: ignore[attr-defined]
            "execute",
            side_effect=SQLAlchemyError("Database error"),
        ):
            result = await repo.get_by_id(user_id)

        assert is_err(result)
        assert result.error.type == RepositoryErrorType.UNEXPECTED
        assert "Database error" in result.error.message


@pytest.mark.anyio
async def test_generic_repository_add_sqlalchemy_error(uow: IUnitOfWork) -> None:
    """Test that add returns RepositoryError on SQLAlchemy error."""
    user = User.register(
        display_name=DisplayName.from_primitive("TestUser").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("test@example.com").expect(
            "Email.from_primitive should succeed"
        ),
    )

    async with uow:
        repo = uow.GetRepository(User)

        # Mock ORMMappingRegistry.to_orm to raise SQLAlchemyError
        with patch.object(
            ORMMappingRegistry,
            "to_orm",
            side_effect=SQLAlchemyError("Conversion error"),
        ):
            result = await repo.add(user)

        assert is_err(result)
        assert result.error.type == RepositoryErrorType.UNEXPECTED
        assert "Conversion error" in result.error.message


@pytest.mark.anyio
async def test_generic_repository_delete_entity_without_id(
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test that delete returns error when entity has no id attribute."""
    from datetime import UTC, datetime

    from sqlalchemy.orm import registry
    from sqlmodel import Field, SQLModel

    @dataclass
    class EntityWithoutId(IAuditable):
        """Dummy entity without id attribute."""

        name: str
        created_at: datetime
        updated_at: datetime

    # Register a dummy ORM mapping for this entity
    class IsolatedModel(SQLModel, registry=registry()):
        pass

    class EntityWithoutIdORM(IsolatedModel, table=True):
        """ORM model for entity without id."""

        __tablename__: str = "entity_without_id"  # type: ignore[assignment]

        name: str = Field(primary_key=True)
        created_at: datetime
        updated_at: datetime

    def to_orm(entity: EntityWithoutId) -> SQLModel:
        return EntityWithoutIdORM(
            name=entity.name,
            created_at=entity.created_at,
            updated_at=entity.updated_at,
        )

    def from_orm(row: SQLModel) -> EntityWithoutId:
        assert isinstance(row, EntityWithoutIdORM)
        return EntityWithoutId(
            name=row.name,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

    for attribute in ("_domain_to_orm", "_to_orm", "_from_orm"):
        monkeypatch.setattr(
            ORMMappingRegistry, attribute, getattr(ORMMappingRegistry, attribute).copy()
        )
    ORMMappingRegistry.register(EntityWithoutId, EntityWithoutIdORM, to_orm, from_orm)

    entity = EntityWithoutId(
        name="test", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )

    async with session_factory() as session:
        repo = GenericRepository(session, EntityWithoutId, None)
        result = await repo.delete(entity)

        assert is_err(result)
        assert result.error.type == RepositoryErrorType.UNEXPECTED
        assert "does not have an id attribute" in result.error.message


@pytest.mark.anyio
async def test_generic_repository_delete_non_existent_entity(
    uow: IUnitOfWork,
) -> None:
    """Test that delete returns NOT_FOUND when entity doesn't exist in database."""
    user = User.register(
        display_name=DisplayName.from_primitive("NonExistent").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("nonexistent@example.com").expect(
            "Email.from_primitive should succeed"
        ),
    )

    async with uow:
        repo = uow.GetRepository(User, UserId)
        result = await repo.delete(user)

        assert is_err(result)
        assert result.error.type == RepositoryErrorType.NOT_FOUND
        assert "not found" in result.error.message


@pytest.mark.anyio
async def test_generic_repository_delete_sqlalchemy_error(uow: IUnitOfWork) -> None:
    """Test that delete returns RepositoryError on SQLAlchemy error."""
    # First create a user
    user = User.register(
        display_name=DisplayName.from_primitive("ToDelete").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("delete@example.com").expect(
            "Email.from_primitive should succeed"
        ),
    )

    async with uow:
        repo = uow.GetRepository(User)
        add_result = await repo.add(user)
        assert is_ok(add_result)
        saved_user = add_result.value
        await uow.commit()

    # Now try to delete with SQLAlchemy error
    async with uow:
        repo = uow.GetRepository(User, UserId)

        # Mock session.execute to raise SQLAlchemyError
        with patch.object(
            repo._session,  # type: ignore[attr-defined]
            "execute",
            side_effect=SQLAlchemyError("Delete error"),
        ):
            result = await repo.delete(saved_user)

        assert is_err(result)
        assert result.error.type == RepositoryErrorType.UNEXPECTED
        assert "Delete error" in result.error.message
