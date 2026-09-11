"""Tests for Discord Times webhook publisher destination validation and sequential delivery."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from flow_res import Ok, Result, is_ok

from app.contracts.messages.times_message import TimesEpisodePlan, TimesPost
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.domain.characters import CharacterDefinition, CharacterRoster
from app.domain.repositories import RepositoryError
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.discord.times_publisher import DiscordWebhookTimesPublisher


class InMemoryTimesStore(ITimesEpisodeStore):
    """In-memory store for tracking delivery progress in tests."""

    def __init__(self) -> None:
        self.plans: dict[str, TimesEpisodePlan] = {}

    async def get(
        self, source_message_id: str
    ) -> Result[TimesEpisodePlan | None, RepositoryError]:
        return Ok(self.plans.get(source_message_id))

    async def save(self, plan: TimesEpisodePlan) -> Result[None, RepositoryError]:
        self.plans[plan.source_message_id] = plan
        return Ok(None)

    async def pending(self) -> Result[list[TimesEpisodePlan], RepositoryError]:
        return Ok(
            [
                p
                for p in self.plans.values()
                if p.status != "COMPLETED" and p.failure is None
            ]
        )

    async def get_recent_completed(
        self, limit: int = 5, *, before: datetime | None = None
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        completed = [p for p in self.plans.values() if p.status == "COMPLETED"]
        return Ok(completed[-limit:])


async def _initialize(publisher: DiscordWebhookTimesPublisher) -> None:
    await publisher.initialize("456", character_channel_ids={"999"})


def _roster() -> CharacterRoster:
    return CharacterRoster(
        characters=(
            CharacterDefinition(
                character_id="maid_a",
                name="Maid_A",
                position="Head Maid",
                responsibilities=("Management",),
                persona="Polite and strict",
                speech_style="Keigo",
                avatar_url="https://example.com/a.png",
            ),
            CharacterDefinition(
                character_id="maid_b",
                name="Maid_B",
                position="Junior Maid",
                responsibilities=("Cleaning",),
                persona="Energetic",
                speech_style="Casual",
                avatar_url="https://example.com/b.png",
            ),
        ),
        common_style=("Always respectful",),
    )


_WEBHOOK_ID = 123456789012345678
_WEBHOOK_URL = f"https://discord.com/api/webhooks/{_WEBHOOK_ID}/" + "a" * 68


@pytest.fixture
def publisher_setup(
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[
    DiscordWebhookTimesPublisher,
    InMemoryTimesStore,
    MagicMock,
    MagicMock,
    list[dict[str, Any]],
]:
    store = InMemoryTimesStore()
    client = MagicMock(spec=discord.Client)
    sent_messages: list[dict[str, Any]] = []

    webhook = MagicMock(spec=discord.Webhook)
    webhook.id = _WEBHOOK_ID
    webhook.guild_id = 456
    webhook.channel_id = 123
    webhook.fetch = AsyncMock(return_value=webhook)

    async def mock_send(**kwargs: Any) -> MagicMock:
        sent_messages.append(kwargs)
        msg = MagicMock(spec=discord.WebhookMessage)
        msg.id = 888 + len(sent_messages)
        return msg

    webhook.send = AsyncMock(side_effect=mock_send)

    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 123
    channel.guild = MagicMock()
    channel.guild.id = 456

    client.fetch_channel = AsyncMock(return_value=channel)
    monkeypatch.setattr(discord.Webhook, "from_url", MagicMock(return_value=webhook))

    publisher = DiscordWebhookTimesPublisher(
        _WEBHOOK_URL,
        client=client,
        store=store,
        roster=_roster(),
    )
    return publisher, store, client, webhook, sent_messages


@pytest.mark.anyio
async def test_initialize_validates_destination_and_sets_scope(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, _, _, _, _ = publisher_setup
    scope = await publisher.initialize("456", character_channel_ids={"999"})
    assert scope == DiscordConversationScope(guild_id="456", channel_id="123")
    assert publisher.webhook_id == _WEBHOOK_ID


@pytest.mark.anyio
async def test_initialize_rejects_foreign_guild(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, _, _, _, _ = publisher_setup
    with pytest.raises(ValueError, match="configured guild"):
        await publisher.initialize("999")


@pytest.mark.anyio
async def test_initialize_rejects_forum_channel(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, _, client, _, _ = publisher_setup
    forum_channel = MagicMock(spec=discord.ForumChannel)
    forum_channel.id = 123
    forum_channel.guild = MagicMock()
    forum_channel.guild.id = 456
    client.fetch_channel = AsyncMock(return_value=forum_channel)

    with pytest.raises(ValueError, match="forum channel"):
        await publisher.initialize("456")


@pytest.mark.anyio
async def test_initialize_rejects_overlap_with_character_response_channel(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, _, _, _, _ = publisher_setup
    with pytest.raises(ValueError, match="character response channel"):
        await publisher.initialize("456", character_channel_ids={"123", "999"})


@pytest.mark.anyio
async def test_deliver_posts_sequentially_with_character_identity(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, _, _, sent_messages = publisher_setup
    await _initialize(publisher)
    plan = TimesEpisodePlan(
        source_message_id="msg_1",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(
            TimesPost(character_name="Maid_A", content="ご主人様、お茶が入りました。"),
            TimesPost(character_name="Maid_B", content="お茶菓子も用意したよ！"),
        ),
        status="DELIVERING",
        next_post_index=0,
    )
    await store.save(plan)

    res = await publisher.deliver(plan)
    assert is_ok(res)
    assert len(sent_messages) == 2
    assert sent_messages[0]["username"] == "Maid_A"
    assert sent_messages[0]["avatar_url"] == "https://example.com/a.png"
    assert sent_messages[0]["content"] == "ご主人様、お茶が入りました。"
    assert sent_messages[1]["username"] == "Maid_B"
    assert sent_messages[1]["avatar_url"] == "https://example.com/b.png"
    assert sent_messages[1]["content"] == "お茶菓子も用意したよ！"

    updated = (await store.get("msg_1")).unwrap()
    assert updated is not None
    assert updated.status == "COMPLETED"
    assert updated.next_post_index == 2


@pytest.mark.anyio
async def test_deliver_splits_long_content_exceeding_discord_limit(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, _, _, sent_messages = publisher_setup
    await _initialize(publisher)
    long_content = ("A" * 1500) + "\n\n" + ("B" * 1500)
    plan = TimesEpisodePlan(
        source_message_id="msg_long",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(TimesPost(character_name="Maid_A", content=long_content),),
        status="DELIVERING",
        next_post_index=0,
    )
    await store.save(plan)

    res = await publisher.deliver(plan)
    assert is_ok(res)
    assert len(sent_messages) == 2
    assert sent_messages[0]["username"] == "Maid_A"
    assert sent_messages[1]["username"] == "Maid_A"


@pytest.mark.anyio
async def test_deliver_empty_posts_is_completed_noop(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, _, _, sent_messages = publisher_setup
    await _initialize(publisher)
    plan = TimesEpisodePlan(
        source_message_id="msg_empty",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(),
        status="PENDING",
        next_post_index=0,
    )
    await store.save(plan)

    res = await publisher.deliver(plan)
    assert is_ok(res)
    assert len(sent_messages) == 0

    updated = (await store.get("msg_empty")).unwrap()
    assert updated is not None
    assert updated.status == "COMPLETED"
    assert updated.next_post_index == 0


@pytest.mark.anyio
async def test_recover_pending_resumes_from_next_post_index(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, _, _, sent_messages = publisher_setup
    await _initialize(publisher)
    # Post 0 was already delivered (next_post_index = 1)
    plan = TimesEpisodePlan(
        source_message_id="msg_partially_delivered",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(
            TimesPost(character_name="Maid_A", content="First post already sent"),
            TimesPost(character_name="Maid_B", content="Second post to recover"),
        ),
        status="DELIVERING",
        next_post_index=1,
    )
    await store.save(plan)

    await publisher.recover_pending()
    assert len(sent_messages) == 1
    assert sent_messages[0]["content"] == "Second post to recover"

    updated = (await store.get("msg_partially_delivered")).unwrap()
    assert updated is not None
    assert updated.status == "COMPLETED"
    assert updated.next_post_index == 2


@pytest.mark.anyio
async def test_delivery_recovery_confirms_an_accepted_post_without_resending(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, client, _, sent_messages = publisher_setup
    await _initialize(publisher)
    plan = TimesEpisodePlan(
        source_message_id="msg_confirmed",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(TimesPost(character_name="Maid_A", content="Already accepted"),),
        status="DELIVERING",
        attempt_started_at=datetime.now(UTC),
    )
    await store.save(plan)

    channel = client.fetch_channel.return_value

    async def history(**_: Any) -> AsyncIterator[discord.Message]:
        message = MagicMock(spec=discord.Message)
        message.webhook_id = _WEBHOOK_ID
        message.content = "Already accepted"
        yield message

    channel.history = history

    result = await publisher.deliver(plan)

    assert is_ok(result)
    assert sent_messages == []
    updated = (await store.get("msg_confirmed")).unwrap()
    assert updated is not None
    assert updated.status == "COMPLETED"
    assert updated.next_post_index == 1


@pytest.mark.anyio
async def test_delivery_recovery_marks_unconfirmed_post_failed_without_resending(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, client, _, sent_messages = publisher_setup
    await _initialize(publisher)
    plan = TimesEpisodePlan(
        source_message_id="msg_unconfirmed",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(TimesPost(character_name="Maid_A", content="Unknown result"),),
        status="DELIVERING",
        attempt_started_at=datetime.now(UTC),
    )
    await store.save(plan)

    channel = client.fetch_channel.return_value

    async def history(**_: Any) -> AsyncIterator[discord.Message]:
        if False:
            yield MagicMock(spec=discord.Message)

    channel.history = history

    result = await publisher.deliver(plan)

    assert not is_ok(result)
    assert sent_messages == []
    updated = (await store.get("msg_unconfirmed")).unwrap()
    assert updated is not None
    assert updated.status == "FAILED"
    assert updated.failure is not None
    assert updated.attempt_started_at is None
