"""Tests for raw chat log query."""

from datetime import UTC, datetime

import pytest
from flow_res import is_ok
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.repositories import IUnitOfWork
from app.domain.value_objects.chat_type import ChatType
from app.infrastructure.orm_models import ChatORM


async def _seed_raw_chat_logs(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Insert chat rows for raw log query tests."""
    async with session_factory() as session:
        session.add_all(
            [
                ChatORM(
                    id="01J0RAWCHAT000000000000001",
                    type="DISCORD",
                    user_id="u1",
                    role="user",
                    message_content={
                        "type": "TEXT",
                        "payload": {"text": "first"},
                    },
                    version=0,
                    created_at=datetime(2026, 5, 20, 8, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 5, 20, 8, 0, tzinfo=UTC),
                    discord_guild_id="guild-1",
                    discord_channel_id="channel-1",
                ),
                ChatORM(
                    id="01J0RAWCHAT000000000000002",
                    type="DISCORD",
                    user_id="u1",
                    role="assistant",
                    message_content={
                        "type": "TEXT",
                        "payload": {"text": "second"},
                    },
                    version=0,
                    created_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 5, 20, 9, 0, tzinfo=UTC),
                    discord_guild_id="guild-1",
                    discord_channel_id="channel-1",
                ),
                ChatORM(
                    id="01J0RAWCHAT000000000000003",
                    type="LINE",
                    user_id="u1",
                    role="user",
                    message_content={
                        "type": "TEXT",
                        "payload": {"text": "ignored"},
                    },
                    version=0,
                    created_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 5, 20, 10, 0, tzinfo=UTC),
                    line_user_id="line-user-1",
                ),
                ChatORM(
                    id="01J0RAWCHAT000000000000004",
                    type="DISCORD",
                    user_id="u2",
                    role="user",
                    message_content={
                        "type": "TEXT",
                        "payload": {"text": "other"},
                    },
                    version=0,
                    created_at=datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
                    updated_at=datetime(2026, 5, 20, 11, 0, tzinfo=UTC),
                    discord_guild_id="guild-2",
                    discord_channel_id="channel-2",
                ),
            ]
        )
        await session.commit()


@pytest.mark.anyio
async def test_raw_chat_log_query_returns_chronological_messages(
    uow: IUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Test raw chat log query ordering and filtering."""
    await _seed_raw_chat_logs(session_factory)

    async with uow:
        query = uow.GetRawChatLogQuery()
        result = await query.get_raw_chat_logs(
            "u1",
            ChatType.DISCORD,
            since=datetime(2026, 5, 20, 8, 30, tzinfo=UTC),
            until=datetime(2026, 5, 20, 9, 30, tzinfo=UTC),
            limit=10,
        )
        assert is_ok(result)
        logs = result.value

        assert len(logs) == 1
        assert logs[0].user_id == "u1"
        assert logs[0].role == "assistant"
        assert logs[0].message_content["payload"]["text"] == "second"


@pytest.mark.anyio
async def test_raw_chat_log_query_lists_distinct_user_ids(
    uow: IUnitOfWork,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Test raw chat log user ID lookup."""

    await _seed_raw_chat_logs(session_factory)

    async with uow:
        query = uow.GetRawChatLogQuery()
        result = await query.list_raw_chat_log_user_ids(
            since=datetime(2026, 5, 20, 8, 0, tzinfo=UTC),
            until=datetime(2026, 5, 20, 12, 0, tzinfo=UTC),
            limit=10,
        )
        assert is_ok(result)
        user_ids = result.value

        assert user_ids == ["u1", "u2"]
