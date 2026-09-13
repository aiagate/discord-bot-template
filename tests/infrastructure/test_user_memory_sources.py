"""Tests for canonical identity and raw-memory source selection."""

from datetime import UTC, datetime

import pytest
from flow_res import is_ok
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.value_objects import ChatPlatform, UserId
from app.infrastructure.orm_models.chat_message_orm import ChatMessageORM
from app.infrastructure.orm_models.memory_consolidated_chat_source_orm import (
    MemoryConsolidatedChatSourceORM,
)
from app.infrastructure.orm_models.user_channel_identity_orm import (
    UserChannelIdentityORM,
)
from app.infrastructure.orm_models.user_orm import UserORM
from app.infrastructure.queries.user_identity_query import SQLAlchemyUserIdentityQuery
from app.infrastructure.queries.user_memory_source_store import (
    SQLAlchemyUserMemorySourceStore,
)


@pytest.mark.anyio
async def test_identity_query_and_pending_sources_respect_owner_and_jst_cutoff(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Resolve explicit identities and select only completed prior JST days."""
    user_id = UserId.generate().expect("test user ID")
    async with session_factory() as session, session.begin():
        session.add(
            UserORM(
                id=user_id.to_primitive(),
                display_name="Alice",
                email="alice@example.com",
                created_at=datetime(2026, 9, 1, tzinfo=UTC),
                updated_at=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )
        session.add(
            UserChannelIdentityORM(
                platform=ChatPlatform.DISCORD.value,
                external_participant_id="discord-alice",
                user_id=user_id.to_primitive(),
            )
        )
        eligible = ChatMessageORM(
            id=UserId.generate().expect("test message ID").to_primitive(),
            platform="DISCORD",
            conversation_scope={
                "platform": "DISCORD",
                "guild_id": "g",
                "channel_id": "c",
            },
            external_sender_id="discord-alice",
            author_kind="user",
            content={"type": "TEXT", "payload": {"text": "前日の発言"}},
            occurred_at=datetime(2026, 9, 11, 14, 0, tzinfo=UTC),
            user_id=user_id.to_primitive(),
        )
        current_jst_day = ChatMessageORM(
            id=UserId.generate().expect("test message ID").to_primitive(),
            platform="DISCORD",
            conversation_scope={
                "platform": "DISCORD",
                "guild_id": "g",
                "channel_id": "c",
            },
            external_sender_id="discord-alice",
            author_kind="user",
            content={"type": "TEXT", "payload": {"text": "当日の発言"}},
            occurred_at=datetime(2026, 9, 11, 16, 0, tzinfo=UTC),
            user_id=user_id.to_primitive(),
        )
        unowned = ChatMessageORM(
            id=UserId.generate().expect("test message ID").to_primitive(),
            platform="DISCORD",
            conversation_scope={
                "platform": "DISCORD",
                "guild_id": "g",
                "channel_id": "c",
            },
            external_sender_id="unknown",
            author_kind="user",
            content={"type": "TEXT", "payload": {"text": "所有者なし"}},
            occurred_at=datetime(2026, 9, 11, 14, 0, tzinfo=UTC),
        )
        session.add_all([eligible, current_jst_day, unowned])
        session.add(
            MemoryConsolidatedChatSourceORM(
                chat_message_id=current_jst_day.id,
                consolidated_at=datetime(2026, 9, 12, tzinfo=UTC),
            )
        )

    identity = SQLAlchemyUserIdentityQuery(session_factory)
    resolved = await identity.resolve(ChatPlatform.DISCORD, "discord-alice")
    unknown = await identity.resolve(ChatPlatform.DISCORD, "unknown")
    assert is_ok(resolved)
    assert is_ok(unknown)
    assert resolved.value == user_id
    assert unknown.value is None

    source_store = SQLAlchemyUserMemorySourceStore(session_factory)
    pending = await source_store.list_pending(
        reference_time=datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
    )
    assert is_ok(pending)
    assert [source.content for source in pending.value] == ["前日の発言"]

    marked = await source_store.mark_processed(
        (eligible.id,), processed_at=datetime(2026, 9, 12, tzinfo=UTC)
    )
    assert is_ok(marked)
    pending_after_mark = await source_store.list_pending(
        reference_time=datetime(2026, 9, 12, 0, 0, tzinfo=UTC)
    )
    assert is_ok(pending_after_mark)
    assert pending_after_mark.value == []
