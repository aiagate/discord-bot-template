"""Regression tests for confirmed, ordered and recoverable Discord delivery."""

import asyncio
from collections.abc import AsyncIterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from flow_res import Err, Ok, Result, is_err, is_ok

from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.messages.speech_message import (
    CharacterSpeechMessage,
    PublishedSpeech,
    SpeechDeliveryPlan,
)
from app.contracts.ports.speech_delivery_store import ISpeechDeliveryStore
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.discord.webhook_publisher import (
    DiscordWebhookSpeechPublisher,
    DiscordWebhookSpeechPublisherRouter,
)

_URL = "https://discord.com/api/webhooks/123456789012345678/" + "a" * 68
_SCOPE = DiscordConversationScope(guild_id="456", channel_id="123")
_FORUM_SCOPE = DiscordConversationScope(guild_id="456", channel_id="789")


class MemoryStore(ISpeechDeliveryStore):
    """Simulate durable state shared across publisher instances."""

    def __init__(self) -> None:
        self.plans: dict[str, SpeechDeliveryPlan] = {}
        self.receipts: dict[str, PublishedSpeech] = {}
        self.fail_receipts = 0

    async def get(
        self, source_message_id: str
    ) -> Result[SpeechDeliveryPlan | None, RepositoryError]:
        return Ok(self.plans.get(source_message_id))

    async def save(
        self, plan: SpeechDeliveryPlan, receipt: PublishedSpeech | None = None
    ) -> Result[None, RepositoryError]:
        if receipt is not None and self.fail_receipts:
            self.fail_receipts -= 1
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED, message="database unavailable"
                )
            )
        self.plans[plan.source_message_id] = plan
        if receipt is not None:
            self.receipts[receipt.external_message_id] = receipt
        return Ok(None)

    async def pending(
        self, scope: DiscordConversationScope
    ) -> Result[list[SpeechDeliveryPlan], RepositoryError]:
        return Ok(
            [
                plan
                for plan in self.plans.values()
                if plan.conversation_scope.guild_id == scope.guild_id
                and plan.delivery_channel_id == scope.channel_id
                and not plan.complete
            ]
        )


@pytest.fixture
async def delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DiscordWebhookSpeechPublisher, MemoryStore, MagicMock, MagicMock, list[MagicMock]
]:
    """Use a local webhook and channel history; never contact Discord."""
    store = MemoryStore()
    webhook = MagicMock(spec=discord.Webhook)
    webhook.id, webhook.guild_id, webhook.channel_id = 999, 456, 123
    webhook.fetch = AsyncMock(return_value=webhook)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id, channel.guild.id = 123, 456
    remote: list[MagicMock] = []

    async def send(**kwargs: Any) -> MagicMock:
        message = MagicMock(spec=discord.WebhookMessage)
        message.id = 800 + len(remote)
        message.channel = channel
        message.author.id = 999
        message.author.display_name = kwargs["username"]
        message.content = kwargs["content"]
        message.created_at = datetime.now(UTC)
        message.webhook_id = 999
        remote.append(message)
        return message

    async def history(**kwargs: Any) -> AsyncIterator[MagicMock]:
        for message in remote:
            if kwargs["after"] < message.created_at < kwargs["before"]:
                yield message

    webhook.send = AsyncMock(side_effect=send)
    channel.history = history
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(discord.Webhook, "from_url", MagicMock(return_value=webhook))
    publisher = DiscordWebhookSpeechPublisher(_URL, client=client, store=store)
    assert await publisher.initialize("456") == _SCOPE
    return publisher, store, webhook, client, remote


@pytest.fixture
async def forum_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DiscordWebhookSpeechPublisher,
    MemoryStore,
    MagicMock,
    MagicMock,
    list[MagicMock],
]:
    """Use a forum webhook and one forum post without contacting Discord."""
    store = MemoryStore()
    webhook = MagicMock(spec=discord.Webhook)
    webhook.id, webhook.guild_id, webhook.channel_id = 999, 456, 123
    webhook.fetch = AsyncMock(return_value=webhook)
    forum = MagicMock(spec=discord.ForumChannel)
    forum.id, forum.guild.id = 123, 456
    thread = MagicMock(spec=discord.Thread)
    thread.id, thread.parent_id, thread.guild.id = 789, 123, 456
    remote: list[MagicMock] = []

    async def send(**kwargs: Any) -> MagicMock:
        assert kwargs["thread"].id == thread.id
        message = MagicMock(spec=discord.WebhookMessage)
        message.id = 800 + len(remote)
        message.channel = thread
        message.author.id = 999
        message.author.display_name = kwargs["username"]
        message.content = kwargs["content"]
        message.created_at = datetime.now(UTC)
        message.webhook_id = 999
        remote.append(message)
        return message

    async def history(**kwargs: Any) -> AsyncIterator[MagicMock]:
        for message in remote:
            if kwargs["after"] < message.created_at < kwargs["before"]:
                yield message

    async def fetch_channel(channel_id: int) -> MagicMock:
        return forum if channel_id == forum.id else thread

    webhook.send = AsyncMock(side_effect=send)
    thread.history = history
    client = MagicMock(spec=discord.Client)
    client.fetch_channel = AsyncMock(side_effect=fetch_channel)
    monkeypatch.setattr(discord.Webhook, "from_url", MagicMock(return_value=webhook))
    publisher = DiscordWebhookSpeechPublisher(_URL, client=client, store=store)
    assert await publisher.initialize("456") == _SCOPE
    assert publisher.is_forum
    return publisher, store, webhook, thread, remote


def _speech(
    content: str = "お帰りなさいませ。", source: str = "100"
) -> CharacterSpeechMessage:
    return CharacterSpeechMessage(
        content=content,
        username="Dorothy",
        avatar_url="https://example.com/avatar.png",
        conversation_scope=_SCOPE,
        source_message_id=source,
        delivery_channel_id=_SCOPE.channel_id,
    )


def _forum_speech(
    content: str = "フォーラムへの返信です。",
    source: str = "100",
    delivery_channel_id: str = "123",
) -> CharacterSpeechMessage:
    return CharacterSpeechMessage(
        content=content,
        username="Dorothy",
        avatar_url="https://example.com/avatar.png",
        conversation_scope=_FORUM_SCOPE,
        source_message_id=source,
        delivery_channel_id=delivery_channel_id,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("master_id", [None, "672491948375932937"])
async def test_recovered_response_allows_only_configured_master_mentions(
    delivery: Any, master_id: str | None
) -> None:
    _, store, webhook, client, _ = delivery
    content = "<@672491948375932937> <@123456789012345678> <@&456> @everyone @here"
    plan = SpeechDeliveryPlan(
        source_message_id="100",
        conversation_scope=_SCOPE,
        username="Dorothy",
        avatar_url=None,
        parts=(content, "続きです。"),
        delivery_channel_id=_SCOPE.channel_id,
    )
    await store.save(plan)
    publisher = DiscordWebhookSpeechPublisher(
        _URL, client=client, store=store, master=DiscordMaster(master_id)
    )
    await publisher.initialize("456")
    await publisher.recover_pending()

    assert store.plans["100"].complete
    assert [call.kwargs["content"] for call in webhook.send.await_args_list] == list(
        plan.parts
    )
    for call in webhook.send.await_args_list:
        assert call.kwargs["allowed_mentions"].to_dict() == (
            {"parse": [], "users": [672491948375932937]}
            if master_id is not None
            else {"parse": []}
        )
    await publisher.recover_pending()
    assert webhook.send.await_count == 2


@pytest.mark.anyio
async def test_invalid_webhook_url_is_rejected_without_exposing_it() -> None:
    with pytest.raises(ValueError, match="Invalid Discord webhook URL"):
        DiscordWebhookSpeechPublisher(
            "https://example.com/secret",
            client=MagicMock(spec=discord.Client),
            store=MemoryStore(),
        )


@pytest.mark.anyio
@pytest.mark.parametrize("invalid_destination", ["guild", "thread"])
async def test_initialization_rejects_foreign_guild_or_thread(
    delivery: Any, invalid_destination: str
) -> None:
    publisher, _, webhook, client, _ = delivery
    if invalid_destination == "guild":
        webhook.guild_id = 457
    else:
        client.fetch_channel.return_value = MagicMock(spec=discord.Thread)
    with pytest.raises(ValueError):
        await publisher.initialize("456")


@pytest.mark.anyio
async def test_waits_for_confirmation_and_preserves_actual_discord_metadata(
    delivery: Any,
) -> None:
    publisher, store, webhook, _, remote = delivery
    assert is_ok(await publisher.publish(_speech()))
    kwargs = webhook.send.await_args.kwargs
    assert kwargs["wait"] is True
    assert kwargs["username"] == "Dorothy"
    assert kwargs["avatar_url"] == "https://example.com/avatar.png"
    assert kwargs["allowed_mentions"].to_dict() == {"parse": []}
    assert kwargs["content"] == "お帰りなさいませ。"
    receipt = store.receipts["800"]
    assert receipt.external_sender_id == "999"
    assert receipt.conversation_scope == _SCOPE
    assert receipt.occurred_at == remote[0].created_at
    assert receipt.content == remote[0].content
    assert receipt.source_message_id == "100"
    assert store.plans["100"].complete


@pytest.mark.anyio
async def test_long_responses_are_serialized_without_interleaving(
    delivery: Any,
) -> None:
    publisher, store, webhook, _, remote = delivery
    started, release = asyncio.Event(), asyncio.Event()
    original_send = webhook.send.side_effect

    async def delayed_send(**kwargs: Any) -> MagicMock:
        if not remote:
            started.set()
            await release.wait()
        return await original_send(**kwargs)

    webhook.send.side_effect = delayed_send
    first = asyncio.create_task(publisher.publish(_speech("第一段落。\n\n" * 1000)))
    await started.wait()
    second = asyncio.create_task(publisher.publish(_speech("次の返信", "101")))
    await asyncio.sleep(0)
    assert webhook.send.await_count == 1
    release.set()
    results = await asyncio.gather(first, second)
    assert all(is_ok(result) for result in results)
    first_parts = store.plans["100"].parts
    assert len(first_parts) > 1
    assert [message.content for message in remote] == [
        *first_parts,
        *store.plans["101"].parts,
    ]
    assert all(
        len(message.content.encode("utf-16-le")) // 2 <= 2000 for message in remote
    )


@pytest.mark.anyio
async def test_failed_history_save_retries_storage_without_resending(
    delivery: Any,
) -> None:
    publisher, store, webhook, _, remote = delivery
    store.fail_receipts = 3
    result = await publisher.publish(_speech("段落。\n\n" * 1000))
    assert is_err(result)
    assert len(remote) == 1
    assert not store.receipts
    assert store.plans["100"].attempt_started_at is not None

    resumed = await publisher.resume(_SCOPE, "100", "123")
    assert is_ok(resumed) and resumed.value is True
    plan = store.plans["100"]
    assert plan.complete
    assert webhook.send.await_count == len(plan.parts)
    assert [item.content for item in remote] == list(plan.parts)
    assert len(store.receipts) == len(plan.parts)


@pytest.mark.anyio
async def test_restart_recovers_confirmed_send_from_discord_history(
    delivery: Any,
) -> None:
    publisher, store, webhook, client, remote = delivery
    store.fail_receipts = 3
    assert is_err(await publisher.publish(_speech()))
    assert len(remote) == 1

    restarted = DiscordWebhookSpeechPublisher(_URL, client=client, store=store)
    await restarted.initialize("456")
    await restarted.recover_pending()
    result = await restarted.resume(_SCOPE, "100", "123")
    assert is_ok(result) and result.value is True
    assert store.plans["100"].complete
    assert len(store.receipts) == 1
    webhook.send.assert_awaited_once()


@pytest.mark.anyio
async def test_uncertain_delivery_stops_resend_but_allows_later_requests(
    delivery: Any,
) -> None:
    publisher, store, webhook, _, _ = delivery
    original_send = webhook.send.side_effect
    webhook.send.side_effect = TimeoutError()
    assert is_err(await publisher.publish(_speech()))
    assert is_err(await publisher.resume(_SCOPE, "100", "123"))
    assert store.plans["100"].failure is not None
    webhook.send.assert_awaited_once()

    webhook.send.side_effect = original_send
    assert is_ok(await publisher.publish(_speech("次の返信", "101")))
    assert webhook.send.await_count == 2


@pytest.mark.anyio
@pytest.mark.parametrize("second_chunk_accepted", [False, True])
async def test_recovery_cannot_reuse_a_receipt_for_identical_chunks(
    delivery: Any, second_chunk_accepted: bool
) -> None:
    publisher, store, webhook, client, remote = delivery
    original_send = webhook.send.side_effect

    async def send(**kwargs: Any) -> MagicMock:
        if remote:
            if second_chunk_accepted:
                await original_send(**kwargs)
            raise TimeoutError("The next chunk was not acknowledged.")
        return await original_send(**kwargs)

    webhook.send.side_effect = send
    repeated_chunk = "A" * 1800
    assert is_err(
        await publisher.publish(_speech(f"{repeated_chunk}\n\n{repeated_chunk}"))
    )

    restarted = DiscordWebhookSpeechPublisher(_URL, client=client, store=store)
    await restarted.initialize("456")
    await restarted.recover_pending()

    plan = store.plans["100"]
    assert plan.complete is second_chunk_accepted
    assert (plan.failure is None) is second_chunk_accepted
    assert [receipt.external_message_id for receipt in plan.delivered] == [
        str(message.id) for message in remote
    ]
    assert webhook.send.await_count == 2


@pytest.mark.anyio
async def test_cancelled_send_remains_recoverable(delivery: Any) -> None:
    publisher, store, webhook, client, _ = delivery
    original_send = webhook.send.side_effect
    sent = asyncio.Event()

    async def lose_acknowledgement(**kwargs: Any) -> None:
        await original_send(**kwargs)
        sent.set()
        await asyncio.Event().wait()

    webhook.send.side_effect = lose_acknowledgement
    task = asyncio.create_task(publisher.publish(_speech()))
    await sent.wait()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert store.plans["100"].attempt_started_at is not None
    restarted = DiscordWebhookSpeechPublisher(_URL, client=client, store=store)
    await restarted.initialize("456")
    await restarted.recover_pending()
    assert store.plans["100"].complete
    webhook.send.assert_awaited_once()


@pytest.mark.anyio
async def test_definite_discord_rejection_is_not_retried(delivery: Any) -> None:
    publisher, store, webhook, _, _ = delivery
    response = MagicMock(status=400, reason="Bad Request")
    webhook.send.side_effect = discord.HTTPException(response, "invalid")
    assert is_err(await publisher.publish(_speech()))
    assert is_err(await publisher.publish(_speech()))
    webhook.send.assert_awaited_once()
    assert store.plans["100"].failure is not None


@pytest.mark.anyio
async def test_moved_webhook_cannot_leak_a_response_to_another_channel(
    delivery: Any,
) -> None:
    publisher, _, webhook, _, _ = delivery
    webhook.channel_id = 124
    assert is_err(await publisher.publish(_speech()))
    webhook.send.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("source", ["", "abc", "１", "1" * 21])
async def test_invalid_source_identity_is_rejected(delivery: Any, source: str) -> None:
    publisher, _, webhook, _, _ = delivery
    assert is_err(await publisher.publish(_speech(source=source)))
    webhook.send.assert_not_awaited()


@pytest.mark.anyio
async def test_duplicate_publish_uses_original_confirmed_plan(delivery: Any) -> None:
    publisher, _, webhook, _, _ = delivery
    assert is_ok(await publisher.publish(_speech()))
    assert is_ok(await publisher.publish(_speech("再生成された別の文章")))
    webhook.send.assert_awaited_once()


@pytest.mark.anyio
async def test_forum_webhook_sends_to_the_source_thread(forum_delivery: Any) -> None:
    publisher, store, webhook, thread, _ = forum_delivery

    result = await publisher.publish(_forum_speech())

    assert is_ok(result)
    assert webhook.send.await_args.kwargs["thread"].id == thread.id
    plan = store.plans["100"]
    assert plan.conversation_scope == _FORUM_SCOPE
    assert plan.delivery_channel_id == "123"


@pytest.mark.anyio
async def test_forum_resume_validates_a_thread_before_reading_a_plan(
    forum_delivery: Any,
) -> None:
    publisher, _, webhook, _, _ = forum_delivery

    result = await publisher.resume(_FORUM_SCOPE, "100", "123")

    assert is_ok(result) and result.value is False
    webhook.send.assert_not_awaited()


@pytest.mark.anyio
async def test_forum_webhook_rejects_a_thread_from_another_forum(
    forum_delivery: Any,
) -> None:
    publisher, _, webhook, thread, _ = forum_delivery
    thread.parent_id = 124

    result = await publisher.publish(_forum_speech())

    assert is_err(result)
    webhook.send.assert_not_awaited()


@pytest.mark.anyio
async def test_webhook_router_uses_the_delivery_channel_for_each_publisher() -> None:
    text_publisher = AsyncMock(spec=DiscordWebhookSpeechPublisher)
    forum_publisher = AsyncMock(spec=DiscordWebhookSpeechPublisher)
    text_publisher.is_forum = False
    forum_publisher.is_forum = True
    text_publisher.publish.return_value = Ok(None)
    forum_publisher.publish.return_value = Ok(None)
    router = DiscordWebhookSpeechPublisherRouter(
        {"123": text_publisher, "321": forum_publisher}
    )

    assert is_ok(await router.publish(_speech()))
    assert is_ok(await router.publish(_forum_speech(delivery_channel_id="321")))

    text_publisher.publish.assert_awaited_once_with(_speech())
    forum_publisher.publish.assert_awaited_once_with(
        _forum_speech(delivery_channel_id="321")
    )


@pytest.mark.anyio
async def test_webhook_router_passes_destination_to_resume() -> None:
    forum_publisher = AsyncMock(spec=DiscordWebhookSpeechPublisher)
    forum_publisher.is_forum = True
    forum_publisher.resume.return_value = Ok(False)
    router = DiscordWebhookSpeechPublisherRouter({"321": forum_publisher})

    result = await router.resume(_FORUM_SCOPE, "100", "321")

    assert is_ok(result) and result.value is False
    forum_publisher.resume.assert_awaited_once_with(_FORUM_SCOPE, "100", "321")


@pytest.mark.anyio
async def test_explicit_text_destination_cannot_override_source_channel(
    delivery: Any,
) -> None:
    """Reject a foreign conversation even if it specifies this webhook destination."""
    publisher, store, webhook, _, _ = delivery
    message = replace(_speech(), conversation_scope=_FORUM_SCOPE)

    assert is_err(await publisher.publish(message))
    assert is_err(await publisher.resume(_FORUM_SCOPE, "100", "123"))
    webhook.send.assert_not_awaited()
    assert not store.plans


@pytest.mark.anyio
async def test_router_rejects_unknown_destination_with_a_single_forum() -> None:
    """An unknown delivery channel cannot be inferred from the configured forums."""
    publisher = AsyncMock(spec=DiscordWebhookSpeechPublisher)
    publisher.is_forum = True
    router = DiscordWebhookSpeechPublisherRouter({"321": publisher})

    assert is_err(await router.publish(_forum_speech(delivery_channel_id="789")))
    assert is_err(await router.resume(_FORUM_SCOPE, "100", "789"))
    publisher.publish.assert_not_awaited()
    publisher.resume.assert_not_awaited()
