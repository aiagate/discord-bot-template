"""SQLAlchemy storage for Times episode plans and delivery progress."""

from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, cast

from flow_res import Err, Ok, Result
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.times_message import TimesEpisodePlan
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.orm_models.times_episode_orm import TimesEpisodeORM

_PLAN = TypeAdapter(TimesEpisodePlan)


def _failure(error: Exception) -> RepositoryError:
    return RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(error))


class SQLAlchemyTimesEpisodeStore(ITimesEpisodeStore):
    """Keep Times episode progress durable across restarts."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(
        self, source_message_id: str
    ) -> Result[TimesEpisodePlan | None, RepositoryError]:
        """Read a persisted plan by source message identity."""
        try:
            async with self._session_factory() as session:
                row = await session.get(TimesEpisodeORM, source_message_id)
                return Ok(None if row is None else _PLAN.validate_python(row.payload))
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))

    async def save(self, plan: TimesEpisodePlan) -> Result[None, RepositoryError]:
        """Atomically persist or update an episode plan."""
        try:
            async with self._session_factory() as session, session.begin():
                row = await session.get(TimesEpisodeORM, plan.source_message_id)
                if row is not None:
                    previous = _PLAN.validate_python(row.payload)
                    if (
                        previous.guild_id,
                        previous.channel_id,
                        previous.delivery_channel_id,
                    ) != (
                        plan.guild_id,
                        plan.channel_id,
                        plan.delivery_channel_id,
                    ):
                        raise ValueError(
                            "An episode already belongs to a different destination."
                        )
                    if previous.context_message_id != plan.context_message_id:
                        raise ValueError("An episode source context cannot change.")
                    if previous.posts and previous.posts != plan.posts:
                        raise ValueError(
                            "An episode already has a different generated plan."
                        )
                    if previous.status == "COMPLETED" and plan.status != "COMPLETED":
                        raise ValueError("A completed episode cannot be reopened.")
                    if previous.failure is not None and plan.failure is None:
                        raise ValueError("A failed episode cannot be reopened.")
                    if previous.next_post_index > plan.next_post_index or (
                        previous.next_post_index == plan.next_post_index
                        and previous.next_chunk_index is not None
                        and (
                            plan.next_chunk_index is None
                            or previous.next_chunk_index > plan.next_chunk_index
                        )
                    ):
                        raise ValueError("Delivery progress cannot move backwards.")
                    if plan.created_at is None:
                        plan = replace(plan, created_at=previous.created_at)
                    elif previous.created_at != plan.created_at:
                        raise ValueError("An episode creation time cannot change.")
                else:
                    created_at = plan.created_at or datetime.now(UTC)
                    if plan.created_at is None:
                        plan = replace(plan, created_at=created_at)
                    row = TimesEpisodeORM(
                        source_message_id=plan.source_message_id,
                        guild_id=plan.guild_id,
                        channel_id=plan.channel_id,
                        status=plan.status,
                        next_post_index=plan.next_post_index,
                        failure=plan.failure,
                        created_at=created_at,
                        payload={},
                    )
                    session.add(row)
                row.status = plan.status
                row.next_post_index = plan.next_post_index
                row.failure = plan.failure
                row.payload = _PLAN.dump_python(plan, mode="json")
            return Ok(None)
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))

    async def pending(
        self, destination: DiscordConversationScope
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        """Return unfinished plans for one Times destination in creation order."""
        try:
            async with self._session_factory() as session:
                table = cast(Any, TimesEpisodeORM).__table__
                rows = await session.scalars(
                    select(TimesEpisodeORM)
                    .where(
                        table.c.guild_id == destination.guild_id,
                        table.c.payload["delivery_channel_id"].as_string()
                        == destination.channel_id,
                        table.c.status != "COMPLETED",
                        table.c.failure.is_(None),
                    )
                    .order_by(table.c.created_at, table.c.source_message_id)
                )
                return Ok([_PLAN.validate_python(row.payload) for row in rows])
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))

    async def get_recent_completed(
        self,
        destination: DiscordConversationScope,
        limit: int = 5,
        *,
        before: datetime | None = None,
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        """Return completed plans for one Times destination for continuity memory."""
        try:
            async with self._session_factory() as session:
                table = cast(Any, TimesEpisodeORM).__table__
                query = select(TimesEpisodeORM).where(
                    table.c.guild_id == destination.guild_id,
                    table.c.payload["delivery_channel_id"].as_string()
                    == destination.channel_id,
                    table.c.status == "COMPLETED",
                )
                if before is not None:
                    query = query.where(table.c.created_at <= before)
                query = query.order_by(table.c.created_at.desc()).limit(limit)
                rows = await session.scalars(query)
                plans = [_PLAN.validate_python(row.payload) for row in rows]
                plans.reverse()
                return Ok(plans)
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))
