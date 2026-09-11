"""Tests for generic repository behavior with append-only ChatMessage."""

from datetime import UTC, datetime

import pytest
from flow_res import is_err, is_ok

from app.contracts.ports import IUnitOfWork
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.repositories import RepositoryErrorType
from app.domain.value_objects import MessageContent


@pytest.mark.anyio
async def test_chat_message_repository_is_append_only(uow: IUnitOfWork) -> None:
    """ChatMessage can be added but cannot be updated."""
    message = ChatMessage.create_discord(
        guild_id="guild-1",
        channel_id="channel-1",
        external_sender_id="user-1",
        content=MessageContent.text("hello"),
        occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
    )
    assert message.is_append_only

    async with uow:
        repository = uow.GetRepository(ChatMessage)
        add_result = await repository.add(message)
        assert is_ok(add_result)

        update_result = await repository.update(add_result.value)

    assert is_err(update_result)
    assert update_result.error.type is RepositoryErrorType.UNEXPECTED
