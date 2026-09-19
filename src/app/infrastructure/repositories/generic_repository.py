"""Generic repository implementation for SQLModel."""

import logging
from datetime import UTC, datetime

from flow_res import Err, Ok, Result, is_err
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.exc import StaleDataError
from sqlmodel import SQLModel

from app.domain.interfaces import IAppendOnly, IAuditable, IValueObject, IVersionable
from app.domain.repositories import (
    IRepositoryWithId,
    RepositoryError,
    RepositoryErrorType,
)
from app.infrastructure.orm_mapping import ORMMappingRegistry

logger = logging.getLogger(__name__)


class GenericRepository[T, K](IRepositoryWithId[T, K]):
    """Persist complete aggregate snapshots through the ORM unit of work."""

    def __init__(
        self, session: AsyncSession, entity_type: type[T], key_type: type[K] | None
    ) -> None:
        self._session = session
        self._entity_type = entity_type
        self._key_type = key_type
        orm_type = ORMMappingRegistry.get_orm_type(entity_type)
        if orm_type is None:
            raise ValueError(f"No ORM mapping found for {entity_type}")
        self._orm_type = orm_type

    def _to_primitive_id(self, id: object) -> object:
        return id.to_primitive() if isinstance(id, IValueObject) else id

    def _get_entity_id(self, entity: T) -> Result[object, RepositoryError]:
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
        return RepositoryError(
            type=RepositoryErrorType.NOT_FOUND,
            message=f"{self._entity_type.__name__} with id {entity_id} not found",
        )

    def _version_conflict_error(self, entity_id: object) -> RepositoryError:
        return RepositoryError(
            type=RepositoryErrorType.VERSION_CONFLICT,
            message=(
                f"Concurrent version modification detected for "
                f"{self._entity_type.__name__} with id {entity_id}"
            ),
        )

    async def _find(self, entity_id: object) -> SQLModel | None:
        statement = select(self._orm_type).where(
            self._orm_type.id == self._to_primitive_id(entity_id)  # type: ignore[attr-defined]
        )
        with self._session.no_autoflush:
            result = await self._session.execute(statement)
        return result.scalar_one_or_none()

    def _write_error(self, error: Exception) -> RepositoryError:
        if isinstance(error, IntegrityError):
            logger.info("Entity constraint conflict: %s", self._entity_type.__name__)
            return RepositoryError(
                type=RepositoryErrorType.ALREADY_EXISTS,
                message=(
                    f"{self._entity_type.__name__} conflicts with an existing "
                    f"record: {error.orig}"
                ),
            )
        logger.exception("Database error occurred in repository")
        return RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(error))

    async def _stale_error(self, entity_id: object) -> RepositoryError:
        await self._session.rollback()
        try:
            existing = await self._find(entity_id)
        except SQLAlchemyError as error:
            await self._session.rollback()
            return self._write_error(error)
        if existing is None:
            return self._not_found_error(entity_id)
        return self._version_conflict_error(entity_id)

    async def get_by_id(self, id: K) -> Result[T, RepositoryError]:
        """Get an aggregate with the relations required by its mapper loaded."""
        try:
            orm_instance = await self._find(id)
            if orm_instance is None:
                return Err(self._not_found_error(id))
            return Ok(ORMMappingRegistry.from_orm(orm_instance))
        except SQLAlchemyError as error:
            await self._session.rollback()
            return Err(self._write_error(error))
        except (TypeError, ValueError) as error:
            return Err(self._write_error(error))

    async def add(self, entity: T) -> Result[T, RepositoryError]:
        """Add an aggregate and flush its owned objects without committing."""
        mutation_started = False
        try:
            orm_instance = ORMMappingRegistry.to_orm(entity)
            entity_id = getattr(entity, "id", None)
            if entity_id is not None and await self._find(entity_id) is not None:
                return Err(
                    RepositoryError(
                        type=RepositoryErrorType.ALREADY_EXISTS,
                        message=(
                            f"{self._entity_type.__name__} with id {entity_id} "
                            "already exists"
                        ),
                    )
                )
            mutation_started = True
            self._session.add(orm_instance)
            await self._session.flush()
            return Ok(ORMMappingRegistry.from_orm(orm_instance))
        except (SQLAlchemyError, TypeError, ValueError) as error:
            if mutation_started or isinstance(error, SQLAlchemyError):
                await self._session.rollback()
            return Err(self._write_error(error))

    def _append_only_error(self, entity: T) -> RepositoryError | None:
        if isinstance(entity, IAppendOnly) and entity.is_append_only:
            return RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message=f"{self._entity_type.__name__} is append-only",
            )
        return None

    async def update(self, entity: T) -> Result[T, RepositoryError]:
        """Replace a full snapshot; empty owned collections remove their children."""
        append_only_error = self._append_only_error(entity)
        if append_only_error is not None:
            return Err(append_only_error)
        entity_id_result = self._get_entity_id(entity)
        if is_err(entity_id_result):
            return Err(entity_id_result.error)
        entity_id = entity_id_result.value
        mutation_started = False
        try:
            orm_instance = ORMMappingRegistry.to_orm(entity)
            with self._session.no_autoflush:
                existing = await self._find(entity_id)
                if existing is None:
                    return Err(self._not_found_error(entity_id))
                if isinstance(entity, IVersionable) and (
                    existing.version != entity.version.to_primitive()  # type: ignore[attr-defined]
                ):
                    return Err(self._version_conflict_error(entity_id))
                if isinstance(entity, IAuditable):
                    created_at = existing.created_at  # type: ignore[attr-defined]
                    if (
                        created_at.tzinfo is None
                        and entity.created_at.tzinfo is not None
                    ):
                        created_at = created_at.replace(tzinfo=UTC)
                    orm_instance.created_at = created_at  # type: ignore[attr-defined]
                    orm_instance.updated_at = datetime.now(UTC)  # type: ignore[attr-defined]
                mutation_started = True
                managed = await self._session.merge(orm_instance, load=True)
                if isinstance(entity, IVersionable):
                    managed.version = entity.version.to_primitive() + 1  # type: ignore[attr-defined]
            await self._session.flush()
            return Ok(ORMMappingRegistry.from_orm(managed))
        except StaleDataError:
            return Err(await self._stale_error(entity_id))
        except (SQLAlchemyError, TypeError, ValueError) as error:
            if mutation_started or isinstance(error, SQLAlchemyError):
                await self._session.rollback()
            return Err(self._write_error(error))

    async def delete(self, entity: T) -> Result[None, RepositoryError]:
        """Delete an aggregate and its owned objects after checking its version."""
        append_only_error = self._append_only_error(entity)
        if append_only_error is not None:
            return Err(append_only_error)
        entity_id_result = self._get_entity_id(entity)
        if is_err(entity_id_result):
            return Err(entity_id_result.error)
        entity_id = entity_id_result.value
        mutation_started = False
        try:
            with self._session.no_autoflush:
                existing = await self._find(entity_id)
                if existing is None:
                    return Err(self._not_found_error(entity_id))
                if isinstance(entity, IVersionable) and (
                    existing.version != entity.version.to_primitive()  # type: ignore[attr-defined]
                ):
                    return Err(self._version_conflict_error(entity_id))
                mutation_started = True
                await self._session.delete(existing)
            await self._session.flush()
            return Ok(None)
        except StaleDataError:
            return Err(await self._stale_error(entity_id))
        except (SQLAlchemyError, TypeError, ValueError) as error:
            if mutation_started or isinstance(error, SQLAlchemyError):
                await self._session.rollback()
            return Err(self._write_error(error))
