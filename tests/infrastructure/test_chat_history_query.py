"""Tests for chat history query."""

from typing import Any, cast

import pytest
from flow_res import is_ok

from app.domain.aggregates.chat import Chat, DiscordChat
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects.chat_type import ChatType
from app.domain.value_objects.message_content import MessageContent


async def _save_chat(uow: IUnitOfWork, content: str, channel_id: str) -> None:
    """Persist a Discord chat message for query tests."""
    async with uow:
        repo = cast(Any, uow.GetRepository(Chat))
        save_result = await repo.add(
            DiscordChat.create(
                guild_id="DM",
                channel_id=channel_id,
                message_content=MessageContent.text(content),
            )
        )
        assert is_ok(save_result)
        commit_result = await uow.commit()
        assert is_ok(commit_result)


@pytest.mark.anyio
async def test_get_recent_history_returns_chronological_order(
    uow: IUnitOfWork,
) -> None:
    """Test recent history order and subtype restoration."""
    await _save_chat(uow, "first", "1")
    await _save_chat(uow, "second", "1")

    async with uow:
        query = uow.GetChatHistoryQuery()
        result = await query.get_recent_history(ChatType.DISCORD, limit=10)
        assert is_ok(result)
        history = result.value

        assert len(history) == 2
        assert [item.message_content.payload["text"] for item in history] == [
            "first",
            "second",
        ]
        assert isinstance(history[0], DiscordChat)
