"""Tests for the dependency injection container."""

import pytest
from flow_res import is_ok
from injector import Injector

from app import container
from app.contracts.ports import ICharacterMemoryStore, IChatHistoryQuery, IUnitOfWork
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.memory import MarkdownCharacterMemoryStore
from app.infrastructure.queries.chat_history_query import SQLAlchemyChatHistoryQuery
from app.infrastructure.repositories.generic_repository import GenericRepository
from app.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


@pytest.mark.anyio
async def test_di_container_bindings(test_db_engine: None) -> None:
    """Test that the DI container is configured correctly."""
    injector = Injector([container.configure])

    query_instance = injector.get(IChatHistoryQuery)
    query_result = await query_instance.get_recent_history(
        DiscordConversationScope(guild_id="guild-1", channel_id="channel-1")
    )

    assert is_ok(query_result)
    assert query_result.value == []

    uow_instance = injector.get(IUnitOfWork)

    assert isinstance(uow_instance, SQLAlchemyUnitOfWork)
    assert isinstance(query_instance, SQLAlchemyChatHistoryQuery)
    assert isinstance(injector.get(ICharacterMemoryStore), MarkdownCharacterMemoryStore)
    async with uow_instance:
        assert isinstance(uow_instance.GetRepository(ChatMessage), GenericRepository)
