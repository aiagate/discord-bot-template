"""Regression tests for ChatMessage save use-case errors."""

from datetime import UTC, datetime
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, Ok, is_err

from app.contracts.ports import IChatHistoryQuery, IUnitOfWork
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import LineConversationScope, MessageContent
from app.usecases.chat.save_discord_chat import (
    SaveDiscordChatCommand,
    SaveDiscordChatHandler,
)
from app.usecases.chat.save_line_chat import SaveLineChatCommand, SaveLineChatHandler
from app.usecases.result import ErrorType


def _mock_uow(repository: object) -> IUnitOfWork:
    """Create a unit-of-work mock with a generic repository."""
    mock_uow = MagicMock(spec=IUnitOfWork)
    mock_uow.GetRepository.return_value = repository
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)
    return cast(IUnitOfWork, mock_uow)


@pytest.mark.anyio
async def test_discord_save_propagates_repository_error() -> None:
    """A repository failure remains internal until the application boundary."""
    repository = MagicMock()
    repository.add = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message="database unavailable",
            )
        )
    )
    handler = SaveDiscordChatHandler(
        _mock_uow(repository), AsyncMock(spec=IChatHistoryQuery)
    )

    result = await handler.handle(
        SaveDiscordChatCommand(
            external_sender_id="user-1",
            guild_id="guild-1",
            channel_id="channel-1",
            content="hello",
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        )
    )

    assert is_err(result)
    assert result.error.type is RepositoryErrorType.UNEXPECTED


@pytest.mark.anyio
async def test_line_save_propagates_commit_error() -> None:
    """A commit failure remains internal until the application boundary."""
    repository = MagicMock()
    message = ChatMessage.create_line(
        conversation_scope=LineConversationScope.group("group-1"),
        external_sender_id="user-1",
        content=MessageContent.text("hello"),
        occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
    )
    repository.add = AsyncMock(return_value=Ok(message))
    uow = _mock_uow(repository)
    uow.commit = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message="commit failed",
            )
        )
    )
    handler = SaveLineChatHandler(uow)

    result = await handler.handle(
        SaveLineChatCommand(
            external_sender_id="user-1",
            conversation_scope=LineConversationScope.group("group-1"),
            content="hello",
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        )
    )

    assert is_err(result)
    assert result.error.type is RepositoryErrorType.UNEXPECTED


@pytest.mark.anyio
async def test_discord_save_rejects_empty_scope_identifiers(
    uow: IUnitOfWork,
) -> None:
    """Invalid conversation locators are reported before persistence."""
    handler = SaveDiscordChatHandler(uow, AsyncMock(spec=IChatHistoryQuery))

    result = await handler.handle(
        SaveDiscordChatCommand(
            external_sender_id="user-1",
            guild_id="",
            channel_id="channel-1",
            content="hello",
            occurred_at=datetime(2026, 9, 5, 9, 0, tzinfo=UTC),
        )
    )

    assert is_err(result)
    assert result.error.type is ErrorType.VALIDATION_ERROR


@pytest.mark.anyio
async def test_discord_save_rejects_naive_occurred_at(
    uow: IUnitOfWork,
) -> None:
    """A naive external timestamp becomes a validation error."""
    handler = SaveDiscordChatHandler(uow, AsyncMock(spec=IChatHistoryQuery))

    result = await handler.handle(
        SaveDiscordChatCommand(
            external_sender_id="user-1",
            guild_id="guild-1",
            channel_id="channel-1",
            content="hello",
            occurred_at=datetime(2026, 9, 5, 9, 0),
        )
    )

    assert is_err(result)
    assert result.error.type is ErrorType.VALIDATION_ERROR
