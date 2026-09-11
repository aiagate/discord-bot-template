"""SQLAlchemy storage for confirmed deliveries and resumable response plans."""

from typing import Any, cast

from flow_res import Err, Ok, Result
from pydantic import TypeAdapter
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.speech_message import PublishedSpeech, SpeechDeliveryPlan
from app.contracts.ports.speech_delivery_store import ISpeechDeliveryStore
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import (
    AuthorKind,
    DiscordConversationScope,
    MessageContent,
)
from app.infrastructure.mappings.chat_message import chat_message_to_orm
from app.infrastructure.orm_models.chat_message_orm import ChatMessageORM
from app.infrastructure.orm_models.speech_delivery_orm import SpeechDeliveryORM

_PLAN = TypeAdapter(SpeechDeliveryPlan)


def _failure(error: Exception) -> RepositoryError:
    return RepositoryError(type=RepositoryErrorType.UNEXPECTED, message=str(error))


class SQLAlchemySpeechDeliveryStore(ISpeechDeliveryStore):
    """Keep progress and delivered ChatMessage rows in the same transaction."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def get(
        self, source_message_id: str
    ) -> Result[SpeechDeliveryPlan | None, RepositoryError]:
        """Read a persisted plan, including completed plans used for deduplication."""
        try:
            async with self._session_factory() as session:
                row = await session.get(SpeechDeliveryORM, source_message_id)
                return Ok(None if row is None else _PLAN.validate_python(row.payload))
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))

    async def save(
        self, plan: SpeechDeliveryPlan, receipt: PublishedSpeech | None = None
    ) -> Result[None, RepositoryError]:
        """Atomically record a plan and its latest confirmed part."""
        try:
            async with self._session_factory() as session, session.begin():
                row = await session.get(SpeechDeliveryORM, plan.source_message_id)
                if row is not None:
                    previous = _PLAN.validate_python(row.payload)
                    if (
                        previous.parts != plan.parts
                        or previous.conversation_scope != plan.conversation_scope
                        or previous.delivery_channel_id != plan.delivery_channel_id
                    ):
                        raise ValueError(
                            "A source message already has a different response plan."
                        )
                    if len(previous.delivered) > len(plan.delivered):
                        raise ValueError("Delivery progress cannot move backwards.")
                else:
                    row = SpeechDeliveryORM(
                        source_message_id=plan.source_message_id,
                        guild_id=plan.conversation_scope.guild_id,
                        channel_id=plan.delivery_channel_id,
                        payload={},
                    )
                    session.add(row)
                row.payload = _PLAN.dump_python(plan, mode="json")
                row.finished = plan.complete or plan.failure is not None
                if receipt is not None:
                    table = cast(Any, ChatMessageORM).__table__
                    existing = await session.scalar(
                        select(ChatMessageORM).where(
                            table.c.platform == "DISCORD",
                            table.c.external_message_id == receipt.external_message_id,
                        )
                    )
                    if existing is None:
                        message = ChatMessage.create_discord(
                            guild_id=receipt.conversation_scope.guild_id,
                            channel_id=receipt.conversation_scope.channel_id,
                            external_sender_id=receipt.external_sender_id,
                            author_kind=AuthorKind.BOT,
                            content=MessageContent.text(receipt.content),
                            occurred_at=receipt.occurred_at,
                            external_message_id=receipt.external_message_id,
                            author_name=receipt.username,
                            reply_to_external_message_id=receipt.source_message_id,
                        )
                        session.add(chat_message_to_orm(message))
            return Ok(None)
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))

    async def pending(
        self, scope: DiscordConversationScope
    ) -> Result[list[SpeechDeliveryPlan], RepositoryError]:
        """Return unfinished plans in the order they were created."""
        try:
            async with self._session_factory() as session:
                table = cast(Any, SpeechDeliveryORM).__table__
                rows = await session.scalars(
                    select(SpeechDeliveryORM)
                    .where(
                        table.c.guild_id == scope.guild_id,
                        table.c.channel_id == scope.channel_id,
                        table.c.finished.is_(False),
                    )
                    .order_by(table.c.created_at, table.c.source_message_id)
                )
                return Ok([_PLAN.validate_python(row.payload) for row in rows])
        except (SQLAlchemyError, ValueError, TypeError) as error:
            return Err(_failure(error))
