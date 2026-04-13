"""Generic repository implementation for SQLModel."""

import logging
from datetime import UTC, datetime
from typing import TypeVar

from flow_res import Err, Ok, Result, is_err
from sqlalchemy import select, update
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.interfaces import IAuditable, IValueObject, IVersionable
from app.domain.repositories import (
    IRepositoryWithId,
    RepositoryError,
    RepositoryErrorType,
)
from app.infrastructure.orm_mapping import ORMMappingRegistry

T = TypeVar("T")
logger = logging.getLogger(__name__)


class GenericRepository[T, K](IRepositoryWithId[T, K]):
    """Generic repository implementation for SQLModel.

    Implements IRepositoryWithId[T, K] (which extends IRepository[T]).

    Type Parameters:
        T: Entity type (e.g., User, Order)
        K: Primary key type (e.g., int, str, UserId) - can be None for repos without get_by_id
    """

    def __init__(
        self, session: AsyncSession, entity_type: type[T], key_type: type[K] | None
    ) -> None:
        self._session = session
        self._entity_type = entity_type
        self._key_type = key_type  # Can be None for repositories without get_by_id

        # Get ORM model class from registry
        orm_type = ORMMappingRegistry.get_orm_type(entity_type)
        if orm_type is None:
            raise ValueError(f"No ORM mapping found for {entity_type}")
        self._orm_type = orm_type

    def _to_primitive_id(self, id: K) -> object:
        """Convert value object ID to primitive type for database query."""
        return (
            id.to_primitive()  # type: ignore[attr-defined]
            if isinstance(id, IValueObject)
            else id
        )

    def _get_entity_id(self, entity: T) -> Result[object, RepositoryError]:
        """Extract and validate entity ID."""
        entity_id = getattr(entity, "id", None)
        if entity_id is None:
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message="Entity does not have an id attribute",
                )
            )
        return Ok(entity_id)

    def _not_found_error(self, entity_id: object) -> RepositoryError:
        """Create a NOT_FOUND error for the given entity ID."""
        return RepositoryError(
            type=RepositoryErrorType.NOT_FOUND,
            message=f"{self._entity_type.__name__} with id {entity_id} not found",
        )

    async def get_by_id(self, id: K) -> Result[T, RepositoryError]:
        """Get entity by ID."""
        try:
            id_value = self._to_primitive_id(id)
            statement = select(self._orm_type).where(self._orm_type.id == id_value)  # type: ignore[attr-defined]
            result = await self._session.execute(statement)
            orm_instance = result.scalar_one_or_none()

            if orm_instance is None:
                return Err(self._not_found_error(id))

            # Use registry for conversion
            return Ok(ORMMappingRegistry.from_orm(orm_instance))
        except SQLAlchemyError as e:
            logger.exception("Database error occurred in get_by_id")
            err = RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(e))
            return Err(err)

    async def add(self, entity: T) -> Result[T, RepositoryError]:
        """Add new entity.

        Returns ALREADY_EXISTS error if entity already exists in the database.
        """
        try:
            # Use registry for conversion
            orm_instance = ORMMappingRegistry.to_orm(entity)

            # Check if entity already exists in database
            entity_id = getattr(entity, "id", None)
            if entity_id is not None and orm_instance.id is not None:  # type: ignore[attr-defined]
                check_stmt = select(self._orm_type).where(
                    self._orm_type.id == orm_instance.id  # type: ignore[attr-defined]
                )
                check_result = await self._session.execute(check_stmt)
                existing = check_result.scalar_one_or_none()
                if existing is not None:
                    return Err(
                        RepositoryError(
                            type=RepositoryErrorType.ALREADY_EXISTS,
                            message=(
                                f"{self._entity_type.__name__} with id {entity_id} "
                                f"already exists"
                            ),
                        )
                    )

            # Insert new entity
            self._session.add(orm_instance)
            await self._session.flush()
            return Ok(ORMMappingRegistry.from_orm(orm_instance))

        except SQLAlchemyError as e:
            logger.exception("Database error occurred in add")
            err = RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(e))
            return Err(err)

    async def update(self, entity: T) -> Result[T, RepositoryError]:
        """Update existing entity with optimistic locking support.

        For entities with a 'version' attribute, implements optimistic locking:
        - Checks current version matches database version
        - Returns VERSION_CONFLICT if versions don't match (concurrent update)
        - Auto-increments version on successful update

        For IAuditable entities, automatically updates the updated_at timestamp.

        Returns NOT_FOUND error if entity doesn't exist in the database.
        """
        try:
            # Use registry for conversion
            orm_instance = ORMMappingRegistry.to_orm(entity)

            entity_id_result = self._get_entity_id(entity)
            if is_err(entity_id_result):
                return entity_id_result  # type: ignore[return-value]
            entity_id = entity_id_result.value

            # Check if entity exists in database
            check_stmt = select(self._orm_type).where(
                self._orm_type.id == orm_instance.id  # type: ignore[attr-defined]
            )
            check_result = await self._session.execute(check_stmt)
            existing = check_result.scalar_one_or_none()

            if existing is None:
                return Err(self._not_found_error(entity_id))

            # Update timestamp for IAuditable entities
            if isinstance(entity, IAuditable):
                orm_instance.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]

            # Check if entity implements IVersionable (optimistic locking)
            if isinstance(entity, IVersionable):
                # Optimistic locking enabled for this entity
                current_version = entity.version.to_primitive()

                # Build UPDATE statement with version check
                # UPDATE table SET col1=val1, version=version+1
                # WHERE id=? AND version=?

                # Get all columns to update from orm_instance
                update_values = {}
                for column in self._orm_type.__table__.columns:  # type: ignore[attr-defined]
                    col_name = column.name
                    if col_name != "id":  # Don't update ID
                        update_values[col_name] = getattr(orm_instance, col_name)

                # Increment version in update
                update_values["version"] = current_version + 1

                # Execute UPDATE with WHERE id=? AND version=?
                stmt = (
                    update(self._orm_type)
                    .where(
                        self._orm_type.id == orm_instance.id,  # type: ignore[attr-defined]
                        self._orm_type.version == current_version,  # type: ignore[attr-defined]
                    )
                    .values(**update_values)
                )

                result = await self._session.execute(stmt)

                # Check if any rows were updated
                if result.rowcount == 0:  # type: ignore[attr-defined]
                    # No rows affected - version mismatch (concurrent update)
                    # Re-fetch to get current version
                    refetch_stmt = select(self._orm_type).where(
                        self._orm_type.id == orm_instance.id  # type: ignore[attr-defined]
                    )
                    refetch_result = await self._session.execute(refetch_stmt)
                    current_entity = refetch_result.scalar_one_or_none()

                    if current_entity is None:
                        # Entity was deleted during update
                        return Err(self._not_found_error(entity_id))

                    err = RepositoryError(
                        type=RepositoryErrorType.VERSION_CONFLICT,
                        message=(
                            f"Concurrent modification detected for "
                            f"{self._entity_type.__name__} with id {entity_id}. "
                            f"Expected version {current_version}, "
                            f"but current version is {current_entity.version}"  # type: ignore[attr-defined]
                        ),
                    )
                    return Err(err)

                # Fetch updated entity to return
                fetch_stmt = select(self._orm_type).where(
                    self._orm_type.id == orm_instance.id  # type: ignore[attr-defined]
                )
                fetch_result = await self._session.execute(fetch_stmt)
                updated_orm = fetch_result.scalar_one()

                return Ok(ORMMappingRegistry.from_orm(updated_orm))
            else:
                # No version field - fall back to merge (legacy behavior)
                orm_instance = await self._session.merge(orm_instance)
                await self._session.flush()
                return Ok(ORMMappingRegistry.from_orm(orm_instance))

        except SQLAlchemyError as e:
            logger.exception("Database error occurred in update")
            err = RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(e))
            return Err(err)

    async def delete(self, entity: T) -> Result[None, RepositoryError]:
        """Delete entity."""
        try:
            entity_id_result = self._get_entity_id(entity)
            if is_err(entity_id_result):
                return entity_id_result  # type: ignore[return-value]
            entity_id = entity_id_result.value

            # Convert value object to primitive type for database query
            id_value = self._to_primitive_id(entity_id)  # type: ignore[arg-type]

            # Fetch the ORM instance from the database
            statement = select(self._orm_type).where(self._orm_type.id == id_value)  # type: ignore[attr-defined]
            result = await self._session.execute(statement)
            orm_instance = result.scalar_one_or_none()

            if orm_instance is None:
                return Err(self._not_found_error(entity_id))

            # Delete the ORM instance
            await self._session.delete(orm_instance)
            return Ok(None)
        except SQLAlchemyError as e:
            logger.exception("Database error occurred in delete")
            err = RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(e))
            return Err(err)
