"""SQLAlchemy Unit of Work implementation."""

import logging
from collections.abc import Callable, Mapping
from typing import Any, cast, overload

from flow_res import Err, Ok, Result
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import Session, SessionTransaction

from app.contracts.ports.unit_of_work import IUnitOfWork
from app.domain.repositories import (
    IRepository,
    IRepositoryWithId,
    RepositoryError,
    RepositoryErrorType,
)
from app.infrastructure.repositories.generic_repository import GenericRepository

logger = logging.getLogger(__name__)

type RepositoryFactories = Mapping[type, Callable[[AsyncSession], object]]


class SQLAlchemyUnitOfWork(IUnitOfWork):
    """Own one Session shared by generic and registered custom repositories."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        repository_factories: RepositoryFactories | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._repository_factories = dict(repository_factories or {})
        self._session: AsyncSession | None = None
        self._repositories: dict[tuple[type, ...], Any] = {}
        self._custom_repositories: dict[type, object] = {}
        self._is_failed = False

    def _require_session(self) -> AsyncSession:
        if self._session is None:
            raise RuntimeError(
                "UnitOfWork session not initialized. Use 'async with' context."
            )
        return self._session

    @overload
    def GetRepository[T](self, entity_type: type[T]) -> IRepository[T]: ...

    @overload
    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K]
    ) -> IRepositoryWithId[T, K]: ...

    def GetRepository[T, K](
        self, entity_type: type[T], key_type: type[K] | None = None
    ) -> IRepository[T] | IRepositoryWithId[T, K]:
        """Get a generic repository cached for the current Session."""
        session = self._require_session()
        cache_key = (entity_type, key_type) if key_type else (entity_type,)
        if cache_key not in self._repositories:
            self._repositories[cache_key] = GenericRepository[T, K](
                session, entity_type, key_type
            )
        return self._repositories[cache_key]

    def GetCustomRepository[R](self, port_type: type[R]) -> R:
        """Get a typed custom port using a factory supplied at composition time."""
        session = self._require_session()
        if port_type not in self._custom_repositories:
            factory = self._repository_factories.get(port_type)
            if factory is None:
                raise ValueError(f"No repository factory registered for {port_type}")
            self._custom_repositories[port_type] = factory(session)
        return cast(R, self._custom_repositories[port_type])

    def _record_rollback(
        self, session: Session, previous_transaction: SessionTransaction
    ) -> None:
        self._is_failed = True

    async def commit(self) -> Result[None, RepositoryError]:
        """Commit unless a repository or database failure invalidated the scope."""
        session = self._require_session()
        if self._is_failed:
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message="Transaction failed; retry in a new UnitOfWork scope.",
                )
            )
        try:
            await session.commit()
            return Ok(None)
        except SQLAlchemyError as error:
            self._is_failed = True
            await session.rollback()
            logger.exception("Database error occurred in commit")
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message=str(error),
                )
            )

    async def rollback(self) -> None:
        """Explicitly discard changes without clearing a prior failure."""
        session = self._require_session()
        was_failed = self._is_failed
        await session.rollback()
        self._is_failed = was_failed

    async def __aenter__(self) -> "SQLAlchemyUnitOfWork":
        """Open a fresh Session and failure state for this scope."""
        if self._session is not None:
            raise RuntimeError("UnitOfWork already has an active scope.")
        session = self._session_factory(close_resets_only=False)
        await session.__aenter__()
        event.listen(session.sync_session, "after_soft_rollback", self._record_rollback)
        self._session = session
        self._is_failed = False
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object | None,
    ) -> None:
        """Roll back uncommitted changes and release all scope-owned objects."""
        if self._session is None:
            return
        session = self._session
        try:
            await session.rollback()
        finally:
            try:
                await session.__aexit__(exc_type, exc_val, exc_tb)
            finally:
                event.remove(
                    session.sync_session, "after_soft_rollback", self._record_rollback
                )
                self._session = None
                self._repositories.clear()
                self._custom_repositories.clear()
