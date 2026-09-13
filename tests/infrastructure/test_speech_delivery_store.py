"""Integration tests for atomic delivery progress and confirmed chat history."""

from dataclasses import replace
from datetime import UTC, datetime

import pytest
from flow_res import is_err, is_ok
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.speech_message import PublishedSpeech, SpeechDeliveryPlan
from app.contracts.ports import IChatHistoryQuery
from app.domain.value_objects import AuthorKind, DiscordConversationScope
from app.infrastructure.queries.speech_delivery_store import (
    SQLAlchemySpeechDeliveryStore,
)

_SCOPE = DiscordConversationScope(guild_id="456", channel_id="123")
_FORUM_SCOPE = DiscordConversationScope(guild_id="456", channel_id="789")


def _plan(source: str = "100") -> SpeechDeliveryPlan:
    return SpeechDeliveryPlan(
        source,
        _SCOPE,
        "Dorothy",
        None,
        ("first", "second"),
        delivery_channel_id=_SCOPE.channel_id,
    )


def _receipt() -> PublishedSpeech:
    return PublishedSpeech(
        external_message_id="800",
        conversation_scope=_SCOPE,
        external_sender_id="999",
        username="Dorothy",
        content="first",
        occurred_at=datetime(2026, 9, 12, 12, tzinfo=UTC),
        source_message_id="100",
    )


def _forum_plan(source: str = "100") -> SpeechDeliveryPlan:
    return SpeechDeliveryPlan(
        source,
        _FORUM_SCOPE,
        "Dorothy",
        None,
        ("first", "second"),
        delivery_channel_id="123",
    )


@pytest.mark.anyio
async def test_confirmed_part_and_progress_are_saved_once_with_provider_metadata(
    session_factory: async_sessionmaker[AsyncSession],
    chat_history_query: IChatHistoryQuery,
) -> None:
    store = SQLAlchemySpeechDeliveryStore(session_factory)
    plan = _plan()
    assert is_ok(await store.save(plan))
    receipt = _receipt()
    confirmed = replace(plan, delivered=(receipt,))
    assert is_ok(await store.save(confirmed, receipt))
    assert is_ok(await store.save(confirmed, receipt))
    restarted = SQLAlchemySpeechDeliveryStore(session_factory)
    loaded = await restarted.get("100")
    assert is_ok(loaded) and loaded.value == confirmed
    history = await chat_history_query.get_recent_history(_SCOPE)
    assert is_ok(history) and len(history.value) == 1
    message = history.value[0]
    assert message.author_kind is AuthorKind.BOT
    assert message.author_name == "Dorothy"
    assert message.external_message_id == "800"
    assert message.external_sender_id.to_primitive() == "999"
    assert message.occurred_at == receipt.occurred_at
    assert message.reply_to_external_message_id == "100"
    assert message.conversation_scope == _SCOPE


@pytest.mark.anyio
async def test_invalid_receipt_rolls_back_both_progress_and_history(
    session_factory: async_sessionmaker[AsyncSession],
    chat_history_query: IChatHistoryQuery,
) -> None:
    store = SQLAlchemySpeechDeliveryStore(session_factory)
    original = replace(_plan(), attempt_started_at=datetime.now(UTC))
    assert is_ok(await store.save(original))
    invalid = replace(_receipt(), occurred_at=datetime(2026, 9, 12))
    result = await store.save(replace(original, delivered=(invalid,)), invalid)
    assert is_err(result)
    persisted = await store.get("100")
    assert is_ok(persisted) and persisted.value == original
    history = await chat_history_query.get_recent_history(_SCOPE)
    assert is_ok(history) and history.value == []


@pytest.mark.anyio
async def test_progress_cannot_be_rewound_or_replaced_with_regenerated_text(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemySpeechDeliveryStore(session_factory)
    confirmed = replace(_plan(), delivered=(_receipt(),))
    assert is_ok(await store.save(confirmed, _receipt()))
    assert is_err(await store.save(_plan()))
    assert is_err(await store.save(replace(confirmed, parts=("different",))))
    assert is_err(await store.save(replace(confirmed, delivery_channel_id="124")))
    assert is_err(
        await store.save(
            replace(
                confirmed,
                conversation_scope=DiscordConversationScope(
                    guild_id="456", channel_id="124"
                ),
            )
        )
    )


@pytest.mark.anyio
async def test_recovery_selects_only_unfinished_plans_in_the_same_channel(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemySpeechDeliveryStore(session_factory)
    first = _plan("100")
    second = _plan("101")
    other_scope = replace(
        _plan("102"),
        conversation_scope=DiscordConversationScope(guild_id="456", channel_id="124"),
        delivery_channel_id="124",
    )
    complete = replace(_plan("103"), parts=("first",), delivered=(_receipt(),))
    failed = replace(_plan("104"), failure="Previous delivery could not be confirmed.")
    for plan in (first, second, other_scope, complete, failed):
        assert is_ok(await store.save(plan))
    pending = await store.pending(_SCOPE)
    assert is_ok(pending) and pending.value == [first, second]
    missing = await store.get("unknown")
    assert is_ok(missing) and missing.value is None


@pytest.mark.anyio
async def test_forum_delivery_is_indexed_by_parent_channel_but_keeps_thread_scope(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemySpeechDeliveryStore(session_factory)
    plan = _forum_plan()

    assert is_ok(await store.save(plan))
    pending = await store.pending(_SCOPE)
    loaded = await store.get(plan.source_message_id)

    assert is_ok(pending) and pending.value == [plan]
    assert is_ok(loaded) and loaded.value == plan
