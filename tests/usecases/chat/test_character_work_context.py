"""Bounded conversation and memory context supplied to Codex work."""

import json
from dataclasses import replace
from datetime import UTC, datetime
from typing import Literal
from unittest.mock import AsyncMock

import pytest
from flow_res import Ok

from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.messages.character_work import CharacterWork, WorkArtifacts
from app.contracts.messages.user_memory import (
    UserMemoryContext,
    UserMemoryProfile,
    UserTimelineEntry,
)
from app.contracts.ports.character_memory_store import ICharacterMemoryStore
from app.contracts.ports.character_work import ICharacterWorkStore
from app.contracts.ports.chat_history_query import IChatHistoryQuery
from app.contracts.ports.user_memory import IUserMemoryStore
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.character_memory import CharacterMemory
from app.domain.value_objects import MessageContent, UserId
from app.usecases.chat.character_work_context import CharacterWorkContextProvider


def _source() -> ChatMessage:
    return ChatMessage.create_discord(
        guild_id="456",
        channel_id="123",
        external_sender_id="2",
        author_name="Alice",
        external_message_id="100",
        content=MessageContent.text("Lilia、前の調査を踏まえて実装して"),
        occurred_at=datetime(2026, 9, 12, 1, 0, tzinfo=UTC),
        user_id=UserId.generate().expect("test user ID"),
    )


def _history_message() -> ChatMessage:
    return ChatMessage.create_discord(
        guild_id="456",
        channel_id="123",
        external_sender_id="2",
        author_name="Alice",
        external_message_id="99",
        content=MessageContent.text("前回は公式資料を優先する方針でした"),
        occurred_at=datetime(2026, 9, 12, 0, 59, tzinfo=UTC),
    )


def _task(*, origin: Literal["discord", "times"] = "discord") -> CharacterWork:
    return CharacterWork(
        id="100",
        guild_id="456",
        channel_id="123",
        owner_id="2",
        character_id="lilia",
        prompt="実装して",
        last_message_id="100",
        origin=origin,
    )


@pytest.mark.anyio
async def test_build_includes_scoped_history_memory_and_reviewed_work() -> None:
    source = _source()
    assert source.user_id is not None
    history_query = AsyncMock(spec=IChatHistoryQuery)
    history_query.get_by_external_id.return_value = Ok(source)
    history_query.get_recent_history.return_value = Ok([_history_message()])

    character_memory = AsyncMock(spec=ICharacterMemoryStore)
    character_memory.get_relevant.return_value = Ok(
        [
            CharacterMemory(
                character_id="lilia",
                source_message_id="memory-1",
                sequence=0,
                content="公式資料を優先する",
                observed_at=datetime(2026, 9, 11, tzinfo=UTC),
            )
        ]
    )
    user_memory = AsyncMock(spec=IUserMemoryStore)
    user_memory.get_context.return_value = Ok(
        UserMemoryContext(
            profile=UserMemoryProfile(
                user_id=source.user_id.to_primitive(),
                summary="調査結果を短く確認したい",
                traits=("慎重",),
                preferences=("出典を確認する",),
                source_message_ids=("memory-source",),
                updated_at=datetime(2026, 9, 11, tzinfo=UTC),
            ),
            timeline=(
                UserTimelineEntry(
                    id="timeline-1",
                    user_id=source.user_id.to_primitive(),
                    day="2026-09-11",
                    title="調査方針",
                    summary="公式資料を優先することにした",
                    source_message_ids=("memory-source",),
                    confidence=1.0,
                    occurred_at=datetime(2026, 9, 11, tzinfo=UTC),
                    updated_at=datetime(2026, 9, 11, tzinfo=UTC),
                ),
            ),
        )
    )
    work_store = AsyncMock(spec=ICharacterWorkStore)
    work_store.recent_reviewed_work.return_value = [
        CharacterWork(
            id="98",
            guild_id="456",
            channel_id="123",
            owner_id="2",
            character_id="noa",
            prompt="前の作業",
            last_message_id="98",
            status="completed",
            review="前回のレビュー済み成果",
            artifacts=WorkArtifacts("r", "sha", 1, 1, "summary"),
        ),
    ]
    provider = CharacterWorkContextProvider(
        history_query,
        character_memory,
        user_memory,
        work_store,
        DiscordMaster(user_id="2", context="成果は短く確認する"),
    )

    payload = json.loads(await provider.build(_task()))

    assert payload["conversation_history"][0]["content"] == (
        "前回は公式資料を優先する方針でした"
    )
    assert payload["master"]["context"] == "成果は短く確認する"
    assert payload["character_memory"][0]["content"] == "公式資料を優先する"
    assert payload["user_memory"]["profile"]["summary"] == ("調査結果を短く確認したい")
    assert payload["completed_work"][0]["summary"] == "前回のレビュー済み成果"
    assert len(payload["completed_work"]) == 1
    history_query.get_recent_history.assert_awaited_once()
    assert history_query.get_recent_history.await_args.kwargs["before"] == (
        source.occurred_at,
        source.id.to_primitive(),
    )
    work_store.recent_reviewed_work.assert_awaited_once_with("456", "123", "2", limit=3)


@pytest.mark.anyio
async def test_times_work_does_not_receive_discord_context() -> None:
    history_query = AsyncMock(spec=IChatHistoryQuery)
    character_memory = AsyncMock(spec=ICharacterMemoryStore)
    user_memory = AsyncMock(spec=IUserMemoryStore)
    work_store = AsyncMock(spec=ICharacterWorkStore)
    provider = CharacterWorkContextProvider(
        history_query,
        character_memory,
        user_memory,
        work_store,
    )

    context = await provider.build(_task(origin="times"))

    assert context == ""
    history_query.get_recent_history.assert_not_awaited()
    character_memory.get_relevant.assert_not_awaited()
    user_memory.get_context.assert_not_awaited()


@pytest.mark.anyio
async def test_context_does_not_cross_work_owner() -> None:
    source = _source()
    history_query = AsyncMock(spec=IChatHistoryQuery)
    history_query.get_by_external_id.return_value = Ok(source)
    character_memory = AsyncMock(spec=ICharacterMemoryStore)
    character_memory.get_relevant.return_value = Ok([])
    user_memory = AsyncMock(spec=IUserMemoryStore)
    work_store = AsyncMock(spec=ICharacterWorkStore)
    work_store.recent_reviewed_work.return_value = []
    provider = CharacterWorkContextProvider(
        history_query,
        character_memory,
        user_memory,
        work_store,
    )

    payload = json.loads(await provider.build(replace(_task(), owner_id="3")))

    assert payload["conversation_history"] == []
    assert payload["user_memory"] is None
    history_query.get_recent_history.assert_not_awaited()
    user_memory.get_context.assert_not_awaited()
