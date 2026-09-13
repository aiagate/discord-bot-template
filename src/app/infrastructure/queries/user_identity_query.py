"""SQLAlchemy provider identity lookup."""

from typing import Any, cast

from flow_res import Err, Ok, Result, is_err
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.ports.user_identity_query import IUserIdentityQuery
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import ChatPlatform, UserId
from app.infrastructure.orm_models.user_channel_identity_orm import (
    UserChannelIdentityORM,
)


class SQLAlchemyUserIdentityQuery(IUserIdentityQuery):
    """Read an explicit provider-to-canonical-user mapping."""

    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> None:
        """Create a query that owns one read session per call."""
        self._session_factory = session_factory

    async def resolve(
        self,
        platform: ChatPlatform,
        external_participant_id: str,
    ) -> Result[UserId | None, RepositoryError]:
        """Return the explicit mapping, never inventing a shared user."""
        try:
            participant_id = external_participant_id.strip()
            if not participant_id:
                raise ValueError("External participant ID cannot be empty.")
            table = cast(Any, UserChannelIdentityORM).__table__
            async with self._session_factory() as session:
                row = await session.scalar(
                    select(UserChannelIdentityORM).where(
                        table.c.platform == platform.to_primitive(),
                        table.c.external_participant_id == participant_id,
                    )
                )
            if row is None:
                return Ok(None)
            user_result = UserId.from_primitive(row.user_id)
            if is_err(user_result):
                raise ValueError(str(user_result.error))
            return Ok(user_result.value)
        except (SQLAlchemyError, TypeError, ValueError) as error:
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message=str(error),
                )
            )
