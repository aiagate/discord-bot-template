"""Tests for save line chat use case."""

import pytest
from flow_res import is_err

from app.domain.repositories import IUnitOfWork
from app.domain.value_objects.chat_type import ChatType
from app.usecases.chat.save_line_chat import SaveChatHandler, SaveLineChatCommand


@pytest.mark.anyio
async def test_save_line_chat_persists_message(
    uow: IUnitOfWork,
) -> None:
    """Test that LINE messages are persisted."""
    handler = SaveChatHandler(uow)

    result = await handler.handle(SaveLineChatCommand(user_id="u1", content="hello"))

    assert not is_err(result)
    assert result.value.id
    async with uow:
        raw_query = uow.GetRawChatLogQuery()
        raw_history = await raw_query.get_raw_chat_logs(
            "u1",
            ChatType.LINE,
            limit=10,
        )
        assert not is_err(raw_history)
        assert len(raw_history.value) == 1
        assert raw_history.value[0].user_id == "u1"
        assert raw_history.value[0].role == "user"
        assert raw_history.value[0].message_content["payload"]["text"] == "hello"

        query = uow.GetChatHistoryQuery()
        history = await query.get_recent_history(ChatType.LINE, limit=10)
        assert not is_err(history)
        assert history.value[-1].message_content.payload["text"] == "hello"
