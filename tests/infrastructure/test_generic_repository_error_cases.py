from flow_res import Err, Ok

"""Tests for GenericRepository error cases to improve coverage."""

from dataclasses import dataclass
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.aggregates.team import Team
from app.domain.aggregates.user import User
from app.domain.interfaces import IAuditable
from app.domain.repositories import IUnitOfWork, RepositoryErrorType
from app.domain.value_objects import (
    DisplayName,
    Email,
    TeamName,
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

        assert isinstance(result, Err)
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

        assert isinstance(result, Err)
        assert result.error.type == RepositoryErrorType.UNEXPECTED
        assert "Conversion error" in result.error.message


@pytest.mark.anyio
async def test_generic_repository_delete_entity_without_id(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Test that delete returns error when entity has no id attribute."""
    from datetime import UTC, datetime

    from sqlmodel import Field, SQLModel

    @dataclass
    class EntityWithoutId(IAuditable):
        """Dummy entity without id attribute."""

        name: str
        created_at: datetime
        updated_at: datetime

    # Register a dummy ORM mapping for this entity
    class EntityWithoutIdORM(SQLModel, table=True):
        """ORM model for entity without id."""

        __tablename__: str = "entity_without_id"  # type: ignore[assignment]

        name: str = Field(primary_key=True)
        created_at: datetime
        updated_at: datetime

    ORMMappingRegistry.register(EntityWithoutId, EntityWithoutIdORM)

    entity = EntityWithoutId(
        name="test", created_at=datetime.now(UTC), updated_at=datetime.now(UTC)
    )

    async with session_factory() as session:
        repo = GenericRepository(session, EntityWithoutId, None)
        result = await repo.delete(entity)

        assert isinstance(result, Err)
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

        assert isinstance(result, Err)
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
        assert isinstance(add_result, Ok)
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

        assert isinstance(result, Err)
        assert result.error.type == RepositoryErrorType.UNEXPECTED
        assert "Delete error" in result.error.message


@pytest.mark.anyio
async def test_generic_repository_update_entity_deleted_during_version_check(
    uow: IUnitOfWork,
) -> None:
    """Test update returns NOT_FOUND when entity is deleted during version check.

    This tests the rare case where:
    1. UPDATE with version check returns rowcount=0
    2. Entity no longer exists (was deleted by another process)
    This covers lines 150-154 in generic_repository.py
    """
    # Create a team
    team = Team.form(
        name=TeamName.from_primitive("Test Team").expect(
            "TeamName.from_primitive should succeed"
        ),
    )

    async with uow:
        repo = uow.GetRepository(Team)
        add_result = await repo.add(team)
        assert isinstance(add_result, Ok)
        saved_team = add_result.value
        await uow.commit()

    # Update team (this will trigger version check)
    updated_team = saved_team.change_name(
        TeamName.from_primitive("Updated Team").expect(
            "TeamName.from_primitive should succeed"
        )
    )

    async with uow:
        repo = uow.GetRepository(Team)

        # Create mock objects for execute results
        # First execute: entity existence check - returns entity exists
        existence_check_mock = MagicMock()
        existence_check_mock.scalar_one_or_none.return_value = (
            MagicMock()
        )  # Entity exists

        # Second execute: UPDATE statement returns rowcount=0 (version mismatch)
        update_result_mock = MagicMock()
        update_result_mock.rowcount = 0

        # Third execute: Re-fetch for version conflict - returns None (entity deleted)
        refetch_mock = MagicMock()
        refetch_mock.scalar_one_or_none.return_value = None  # Entity was deleted

        # Mock session.execute to return different results for each call
        execute_mock = AsyncMock()
        execute_mock.side_effect = [
            existence_check_mock,
            update_result_mock,
            refetch_mock,
        ]

        with patch.object(
            repo._session,  # type: ignore[attr-defined]
            "execute",
            execute_mock,  # type: ignore[attr-defined]
        ):
            result = await repo.update(updated_team)

        assert isinstance(result, Err)
        assert result.error.type == RepositoryErrorType.NOT_FOUND
        assert "not found" in result.error.message
        # Verify execute was called three times (existence check + UPDATE + refetch)
        assert execute_mock.call_count == 3
