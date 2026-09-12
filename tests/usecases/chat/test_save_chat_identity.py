"""Tests for attaching canonical ownership during chat ingestion."""

from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Ok, is_ok

from app.contracts.ports import IChatHistoryQuery, IUnitOfWork, IUserIdentityQuery
from app.domain.value_objects import ChatPlatform, UserId
from app.usecases.chat.save_discord_chat import (
    SaveDiscordChatCommand,
    SaveDiscordChatHandler,
)


@pytest.mark.anyio
async def test_discord_ingestion_attaches_explicit_canonical_user(
    uow: IUnitOfWork,
    chat_history_query: IChatHistoryQuery,
) -> None:
    """Resolve provider identity before persisting the immutable raw row."""
    identity = MagicMock(spec=IUserIdentityQuery)
    user_id = UserId.generate().expect("test user ID")
    identity.resolve = AsyncMock(return_value=Ok(user_id))
    handler = SaveDiscordChatHandler(uow, chat_history_query, identity)

    result = await handler.handle(
        SaveDiscordChatCommand(
            external_sender_id="discord-alice",
            guild_id="guild",
            channel_id="channel",
            content="hello",
            occurred_at=datetime(2026, 9, 11, tzinfo=UTC),
            external_message_id="discord-message",
        )
    )

    assert is_ok(result)
    identity.resolve.assert_awaited_once_with(ChatPlatform.DISCORD, "discord-alice")
    saved = await chat_history_query.get_by_external_id(
        ChatPlatform.DISCORD, "discord-message"
    )
    assert is_ok(saved)
    assert saved.value is not None
    assert saved.value.user_id == user_id
