"""Tests for Discord Times webhook publisher destination validation and sequential delivery."""

from collections.abc import AsyncIterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest
from flow_res import Err, Ok, Result, is_err, is_ok
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.messages.times_message import TimesEpisodePlan, TimesPost
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.domain.character_memory import CharacterMemory
from app.domain.characters import CharacterDefinition, CharacterRoster
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.discord.times_publisher import DiscordWebhookTimesPublisher
from app.infrastructure.memory.character_memory_store import (
    MarkdownCharacterMemoryStore,
)
from app.infrastructure.orm_models.times_episode_orm import TimesEpisodeORM
from app.infrastructure.queries.times_episode_store import SQLAlchemyTimesEpisodeStore


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

    async def pending(
        self, destination: DiscordConversationScope
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        return Ok(
            [
                p
                for p in self.plans.values()
                if p.status != "COMPLETED"
                and p.failure is None
                and (p.guild_id, p.delivery_channel_id)
                == (destination.guild_id, destination.channel_id)
            ]
        )

    async def get_recent_completed(
        self,
        destination: DiscordConversationScope,
        limit: int = 5,
        *,
        before: datetime | None = None,
    ) -> Result[list[TimesEpisodePlan], RepositoryError]:
        completed = [
            p
            for p in self.plans.values()
            if p.status == "COMPLETED"
            and (p.guild_id, p.delivery_channel_id)
            == (destination.guild_id, destination.channel_id)
        ]
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
def character_memory_store(tmp_path: Path) -> MarkdownCharacterMemoryStore:
    return MarkdownCharacterMemoryStore(tmp_path)


@pytest.fixture
def publisher_setup(
    monkeypatch: pytest.MonkeyPatch,
    character_memory_store: MarkdownCharacterMemoryStore,
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
        msg.created_at = datetime(2026, 9, 12, 3, tzinfo=UTC) + timedelta(
            seconds=len(sent_messages)
        )
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
        memory_store=character_memory_store,
        roster=_roster(),
    )
    return publisher, store, client, webhook, sent_messages


@pytest.mark.anyio
@pytest.mark.parametrize("master_id", [None, "672491948375932937"])
async def test_recovered_times_posts_allow_only_configured_master_mentions(
    publisher_setup: Any,
    master_id: str | None,
    character_memory_store: MarkdownCharacterMemoryStore,
) -> None:
    _, store, client, webhook, sent_messages = publisher_setup
    content = "<@672491948375932937> <@123456789012345678> <@&456> @everyone @here"
    plan = TimesEpisodePlan(
        source_message_id="100",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(
            TimesPost(character_name="Maid_A", content=content),
            TimesPost(character_name="Maid_B", content="お茶菓子も用意しました。"),
        ),
        status="DELIVERING",
        next_post_index=0,
    )
    await store.save(plan)
    publisher = DiscordWebhookTimesPublisher(
        _WEBHOOK_URL,
        client=client,
        store=store,
        memory_store=character_memory_store,
        roster=_roster(),
        master=DiscordMaster(master_id),
    )
    await _initialize(publisher)
    await publisher.recover_pending()

    assert store.plans["100"].complete
    assert [message["content"] for message in sent_messages] == [
        post.content for post in plan.posts
    ]
    for message in sent_messages:
        assert message["allowed_mentions"].to_dict() == (
            {"parse": [], "users": [672491948375932937]}
            if master_id is not None
            else {"parse": []}
        )
    await publisher.recover_pending()
    assert webhook.send.await_count == 2


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
    assert sent_messages[0]["username"] == "Maid_A【Head Maid】"
    assert sent_messages[0]["avatar_url"] == "https://example.com/a.png"
    assert sent_messages[0]["content"] == "ご主人様、お茶が入りました。"
    assert sent_messages[1]["username"] == "Maid_B【Junior Maid】"
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
    assert sent_messages[0]["username"] == "Maid_A【Head Maid】"
    assert sent_messages[1]["username"] == "Maid_A【Head Maid】"


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
        message.id = 889
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


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ["acknowledgement", "progress_save"])
async def test_restart_recovers_a_multipart_post_without_resending_confirmed_chunks(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
    session_factory: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    publisher, _, client, webhook, sent_messages = publisher_setup
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    publisher._store = store
    await _initialize(publisher)
    original_send = webhook.send.side_effect
    original_save = store.save

    async def send(**kwargs: Any) -> discord.WebhookMessage:
        message = await original_send(**kwargs)
        if failure_stage == "acknowledgement" and len(sent_messages) == 2:
            raise TimeoutError("Discord accepted the chunk but its response was lost.")
        return message

    async def save(plan: TimesEpisodePlan) -> Result[None, RepositoryError]:
        if failure_stage == "progress_save" and len(sent_messages) == 2:
            return Err(
                RepositoryError(
                    type=RepositoryErrorType.UNEXPECTED,
                    message="Progress could not be committed.",
                )
            )
        return await original_save(plan)

    webhook.send = AsyncMock(side_effect=send)
    monkeypatch.setattr(store, "save", save)
    contents = ["A" * 1800, "B" * 1800, "C" * 100]
    plan = TimesEpisodePlan(
        source_message_id="multipart",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(TimesPost(character_name="Maid_A", content="\n\n".join(contents)),),
        status="DELIVERING",
    )
    assert is_ok(await store.save(plan))
    assert is_err(await publisher.deliver(plan))
    assert [message["content"] for message in sent_messages] == contents[:2]
    interrupted = (await store.get(plan.source_message_id)).unwrap()
    assert interrupted is not None
    assert interrupted.next_post_index == 0
    assert interrupted.next_chunk_index == 1
    assert interrupted.last_message_id == "889"

    async def history(**_: Any) -> AsyncIterator[discord.Message]:
        message = MagicMock(spec=discord.Message)
        message.webhook_id = _WEBHOOK_ID
        message.content = contents[1]
        message.id = 890
        yield message

    client.fetch_channel.return_value.history = history
    webhook.send = AsyncMock(side_effect=original_send)
    restarted_store = SQLAlchemyTimesEpisodeStore(session_factory)
    restarted_publisher = DiscordWebhookTimesPublisher(
        _WEBHOOK_URL,
        client=client,
        store=restarted_store,
        memory_store=publisher._memory_store,
        roster=_roster(),
    )
    await _initialize(restarted_publisher)
    await restarted_publisher.recover_pending()

    assert [message["content"] for message in sent_messages] == contents
    completed = (await restarted_store.get(plan.source_message_id)).unwrap()
    assert completed is not None and completed.status == "COMPLETED"
    assert completed.next_post_index == 1
    assert completed.next_chunk_index == 0
    assert completed.last_message_id == "891"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "other_destination",
    [
        DiscordConversationScope(guild_id="456", channel_id="777"),
        DiscordConversationScope(guild_id="888", channel_id="123"),
    ],
)
async def test_recovery_leaves_other_times_destinations_pending_without_blocking_this_one(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
    session_factory: async_sessionmaker[AsyncSession],
    other_destination: DiscordConversationScope,
) -> None:
    publisher, _, _, _, sent_messages = publisher_setup
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    publisher._store = store
    await _initialize(publisher)
    other_plan = TimesEpisodePlan(
        source_message_id="other-times-destination",
        guild_id=other_destination.guild_id,
        channel_id="999",
        delivery_channel_id=other_destination.channel_id,
        posts=(TimesPost(character_name="Maid_A", content="Other destination's post"),),
        status="DELIVERING",
    )
    current_plan = TimesEpisodePlan(
        source_message_id="current-times-destination",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(
            TimesPost(character_name="Maid_A", content="Current destination's post"),
        ),
        status="DELIVERING",
    )
    assert is_ok(await store.save(other_plan))
    assert is_ok(await store.save(current_plan))

    await publisher.recover_pending()

    assert [message["content"] for message in sent_messages] == [
        "Current destination's post"
    ]
    pending = (await store.get(other_plan.source_message_id)).unwrap()
    assert pending is not None and pending.status == "DELIVERING"


@pytest.mark.anyio
async def test_recovery_does_not_confirm_a_repeated_chunk_with_an_earlier_message(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
) -> None:
    publisher, store, client, webhook, sent_messages = publisher_setup
    await _initialize(publisher)
    original_send = webhook.send.side_effect

    async def send(**kwargs: Any) -> discord.WebhookMessage:
        if sent_messages:
            raise TimeoutError("The next chunk may not have reached Discord.")
        return await original_send(**kwargs)

    webhook.send = AsyncMock(side_effect=send)
    repeated_chunk = "A" * 1800
    plan = TimesEpisodePlan(
        source_message_id="repeated-chunks",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(
            TimesPost(
                character_name="Maid_A",
                content=f"{repeated_chunk}\n\n{repeated_chunk}",
            ),
        ),
        status="DELIVERING",
    )
    assert is_err(await publisher.deliver(plan))
    assert len(sent_messages) == 1

    async def history(**_: Any) -> AsyncIterator[discord.Message]:
        message = MagicMock(spec=discord.Message)
        message.id = 889
        message.webhook_id = _WEBHOOK_ID
        message.content = repeated_chunk
        yield message

    client.fetch_channel.return_value.history = history
    restarted = DiscordWebhookTimesPublisher(
        _WEBHOOK_URL,
        client=client,
        store=store,
        memory_store=publisher._memory_store,
        roster=_roster(),
    )
    await _initialize(restarted)
    await restarted.recover_pending()

    updated = (await store.get(plan.source_message_id)).unwrap()
    assert updated is not None and updated.status == "FAILED"
    assert updated.next_post_index == 0
    assert updated.next_chunk_index == 1
    assert len(sent_messages) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("confirmed_chunks", [1, 2])
async def test_recovery_of_saved_post_progress_never_resends_legacy_chunks(
    publisher_setup: tuple[
        DiscordWebhookTimesPublisher,
        InMemoryTimesStore,
        MagicMock,
        MagicMock,
        list[dict[str, Any]],
    ],
    session_factory: async_sessionmaker[AsyncSession],
    confirmed_chunks: int,
) -> None:
    publisher, _, client, _, sent_messages = publisher_setup
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    publisher._store = store
    await _initialize(publisher)
    chunks = ["A" * 1800, "B" * 1800]
    plan = TimesEpisodePlan(
        source_message_id="legacy-inflight-post",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(TimesPost(character_name="Maid_A", content="\n\n".join(chunks)),),
        status="DELIVERING",
        attempt_started_at=datetime.now(UTC),
    )
    assert is_ok(await store.save(plan))
    async with session_factory() as session, session.begin():
        row = await session.get(TimesEpisodeORM, plan.source_message_id)
        assert row is not None
        row.payload = {
            key: value
            for key, value in row.payload.items()
            if key not in {"next_chunk_index", "last_message_id"}
        }

    async def history(**_: Any) -> AsyncIterator[discord.Message]:
        for index, content in enumerate(chunks[:confirmed_chunks]):
            message = MagicMock(spec=discord.Message)
            message.id = 889 + index
            message.webhook_id = _WEBHOOK_ID
            message.content = content
            yield message

    client.fetch_channel.return_value.history = history
    await publisher.recover_pending()

    assert sent_messages == []
    updated = (await store.get(plan.source_message_id)).unwrap()
    assert updated is not None
    if confirmed_chunks == len(chunks):
        assert updated.status == "COMPLETED"
        assert updated.next_post_index == 1
        assert updated.last_message_id == "890"
    else:
        assert updated.status == "FAILED"
        assert updated.next_post_index == 0


@pytest.mark.anyio
@pytest.mark.parametrize("interrupt_last_chunk", [False, True])
async def test_times_remembers_only_fully_delivered_posts(
    publisher_setup: Any,
    character_memory_store: MarkdownCharacterMemoryStore,
    interrupt_last_chunk: bool,
) -> None:
    """Keep confirmed speakers' notes separate from ordinary conversation memory."""
    publisher, _, _, webhook, sent_messages = publisher_setup
    await _initialize(publisher)
    ordinary = CharacterMemory(
        character_id="maid_a",
        source_message_id="100",
        sequence=0,
        content="通常返信の記憶。",
        observed_at=datetime(2026, 9, 12, 2, tzinfo=UTC),
    )
    assert is_ok(await character_memory_store.save([ordinary]))
    original_send = webhook.send.side_effect

    async def send(**kwargs: Any) -> discord.WebhookMessage:
        if interrupt_last_chunk and len(sent_messages) == 2:
            raise TimeoutError("The final chunk was not acknowledged.")
        return await original_send(**kwargs)

    webhook.send = AsyncMock(side_effect=send)
    plan = TimesEpisodePlan(
        source_message_id="100",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(
            TimesPost(
                character_name="Maid_A",
                content="時刻の話をしよう。",
                memory_candidates=("Timesで時刻の話を始めた。",),
                selection_summary="時刻の話を仲間としている。",
            ),
            TimesPost(
                character_name="Maid_B",
                content="B" * 3000,
                memory_candidates=("Timesで時刻への意見を述べた。",),
                selection_summary="時刻について意見を述べた。",
            ),
        ),
        status="DELIVERING",
    )

    assert is_ok(await publisher.deliver(plan)) is not interrupt_last_chunk

    memories = (
        await character_memory_store.get_relevant(character_id="maid_a")
    ).unwrap()
    assert [memory.content for memory in memories] == [
        ordinary.content,
        "Timesで時刻の話を始めた。",
    ]
    assert memories[1].source_message_id == "times:100:00"
    assert memories[1].observed_at == datetime(2026, 9, 12, 3, 0, 1, tzinfo=UTC)
    other_memories = (
        await character_memory_store.get_relevant(character_id="maid_b")
    ).unwrap()
    assert [memory.content for memory in other_memories] == (
        [] if interrupt_last_chunk else ["Timesで時刻への意見を述べた。"]
    )
    summaries = (
        await character_memory_store.get_selection_summaries(
            character_ids=("maid_a", "maid_b")
        )
    ).unwrap()
    assert set(summaries) == (
        {"maid_a"} if interrupt_last_chunk else {"maid_a", "maid_b"}
    )
    assert summaries["maid_a"].content == "時刻の話を仲間としている。"
    assert all("memory_candidates" not in message for message in sent_messages)


@pytest.mark.anyio
@pytest.mark.parametrize("failure_stage", ["memory", "summary", "progress"])
async def test_times_recovers_memory_without_resending_the_confirmed_post(
    publisher_setup: Any,
    character_memory_store: MarkdownCharacterMemoryStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    failure_stage: str,
) -> None:
    """Retry persisted notes and summaries after a write or progress failure."""
    publisher, store, client, _, sent_messages = publisher_setup
    await _initialize(publisher)
    target = store if failure_stage == "progress" else character_memory_store
    method = "save_selection_summary" if failure_stage == "summary" else "save"
    original = getattr(target, method)

    async def fail_write(value: Any) -> Result[None, RepositoryError]:
        if failure_stage == "progress" and value.next_post_index == 0:
            return await original(value)
        if failure_stage != "progress":
            assert is_ok(await original(value))
        return Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message="Write acknowledgement was lost.",
            )
        )

    monkeypatch.setattr(target, method, fail_write)
    post = TimesPost(
        character_name="Maid_A",
        content="仲間と話した。",
        memory_candidates=("Timesで仲間と話した。",),
        selection_summary="仲間との会話が続いている。",
    )
    plan = TimesEpisodePlan(
        source_message_id="100",
        guild_id="456",
        channel_id="999",
        delivery_channel_id="123",
        posts=(post,),
        status="DELIVERING",
    )
    assert is_err(await publisher.deliver(plan))
    assert len(sent_messages) == 1
    assert store.plans["100"].next_post_index == 0
    assert store.plans["100"].attempt_started_at is not None

    async def history(**_: Any) -> AsyncIterator[discord.Message]:
        message = MagicMock(spec=discord.Message)
        message.id = 889
        message.webhook_id = _WEBHOOK_ID
        message.content = post.content
        message.created_at = datetime(2026, 9, 12, 3, 0, 1, tzinfo=UTC)
        yield message

    client.fetch_channel.return_value.history = history
    monkeypatch.setattr(target, method, original)
    restarted_memory = MarkdownCharacterMemoryStore(tmp_path)
    restarted = DiscordWebhookTimesPublisher(
        _WEBHOOK_URL,
        client=client,
        store=store,
        memory_store=restarted_memory,
        roster=_roster(),
    )
    await _initialize(restarted)
    await restarted.recover_pending()

    assert len(sent_messages) == 1
    assert store.plans["100"].complete
    notes = (await restarted_memory.get_relevant(character_id="maid_a")).unwrap()
    assert len(notes) == 1
    assert notes[0].content == post.memory_candidates[0]
    assert notes[0].source_message_id == "times:100:00"
    summaries = (
        await restarted_memory.get_selection_summaries(character_ids=("maid_a",))
    ).unwrap()
    assert summaries["maid_a"].content == post.selection_summary
