"""Tests for SQLAlchemyTimesEpisodeStore persistence, progress, and ordering."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest
from flow_res import is_err, is_ok
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.times_message import (
    TimesEpisodePlan,
    TimesPost,
    TimesWorkIntent,
)
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.queries.times_episode_store import SQLAlchemyTimesEpisodeStore

_DESTINATION = DiscordConversationScope(guild_id="456", channel_id="999")


@pytest.mark.anyio
async def test_times_episode_store_lifecycle_and_progress(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyTimesEpisodeStore(session_factory)

    # Initially None
    res = await store.get("source_1")
    assert is_ok(res)
    assert res.value is None

    # Save initial pending plan
    now = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)
    plan = TimesEpisodePlan(
        source_message_id="source_1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(),
        status="PENDING",
        next_post_index=0,
        created_at=now,
    )
    save_res = await store.save(plan)
    assert is_ok(save_res)

    fetched = (await store.get("source_1")).unwrap()
    assert fetched is not None
    assert fetched.status == "PENDING"
    assert fetched.posts == ()
    assert fetched.next_post_index == 0
    assert fetched.channel_id == "123"
    assert fetched.delivery_channel_id == "999"
    assert is_err(await store.save(replace(plan, delivery_channel_id="777")))

    # Save generated posts
    posts = (
        TimesPost(
            character_name="Dorothy",
            content="A" * 3000,
            memory_candidates=("Timesで仲間と時刻の基準を確認した。",),
            selection_summary="時刻の基準を共有済み。",
        ),
        TimesPost(character_name="Elinor", content="Post 2"),
    )
    plan_with_posts = TimesEpisodePlan(
        source_message_id="source_1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=posts,
        status="DELIVERING",
        next_post_index=0,
        created_at=now,
    )
    save_res = await store.save(plan_with_posts)
    assert is_ok(save_res)

    changed_posts = (
        TimesPost(character_name="Dorothy", content="Changed post 1"),
        TimesPost(character_name="Elinor", content="Post 2"),
    )
    assert is_err(
        await store.save(
            TimesEpisodePlan(
                source_message_id="source_1",
                guild_id="456",
                channel_id="123",
                delivery_channel_id="999",
                posts=changed_posts,
                status="DELIVERING",
                next_post_index=0,
                created_at=now,
            )
        )
    )

    fetched = (await store.get("source_1")).unwrap()
    assert fetched is not None
    assert fetched.status == "DELIVERING"
    assert len(fetched.posts) == 2
    assert fetched.posts == posts

    partial = replace(plan_with_posts, next_chunk_index=1)
    assert is_ok(await store.save(partial))
    persisted = (await store.get("source_1")).unwrap()
    assert persisted is not None
    assert persisted.next_post_index == 0
    assert persisted.next_chunk_index == 1
    assert is_err(await store.save(plan_with_posts))

    # Advance progress
    plan_advanced = TimesEpisodePlan(
        source_message_id="source_1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=posts,
        status="DELIVERING",
        next_post_index=1,
        created_at=now,
    )
    save_res = await store.save(plan_advanced)
    assert is_ok(save_res)

    # Progress cannot move backwards
    plan_backwards = TimesEpisodePlan(
        source_message_id="source_1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=posts,
        status="DELIVERING",
        next_post_index=0,
        created_at=now,
    )
    save_backwards = await store.save(plan_backwards)
    assert is_err(save_backwards)

    # Mark completed
    plan_completed = TimesEpisodePlan(
        source_message_id="source_1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=posts,
        status="COMPLETED",
        next_post_index=2,
        created_at=now,
    )
    save_completed = await store.save(plan_completed)
    assert is_ok(save_completed)


@pytest.mark.anyio
async def test_times_episode_store_pending_and_completed_queries(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    base_time = datetime(2026, 9, 12, 10, 0, tzinfo=UTC)

    # Create 3 episodes: 2 completed, 1 pending
    ep1 = TimesEpisodePlan(
        source_message_id="ep_1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Dorothy", content="First ep"),),
        status="COMPLETED",
        next_post_index=1,
        created_at=base_time,
    )
    ep2 = TimesEpisodePlan(
        source_message_id="ep_2",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Elinor", content="Second ep"),),
        status="COMPLETED",
        next_post_index=1,
        created_at=base_time + timedelta(minutes=5),
    )
    ep3 = TimesEpisodePlan(
        source_message_id="ep_3",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(),
        status="PENDING",
        next_post_index=0,
        created_at=base_time + timedelta(minutes=10),
    )

    await store.save(ep1)
    await store.save(ep2)
    await store.save(ep3)

    # pending() returns unfinished episodes (ep3)
    pending_res = await store.pending(_DESTINATION)
    assert is_ok(pending_res)
    assert len(pending_res.value) == 1
    assert pending_res.value[0].source_message_id == "ep_3"

    # get_recent_completed() returns completed in chronological order
    completed_res = await store.get_recent_completed(_DESTINATION, limit=5)
    assert is_ok(completed_res)
    assert len(completed_res.value) == 2
    assert completed_res.value[0].source_message_id == "ep_1"
    assert completed_res.value[1].source_message_id == "ep_2"

    # with before filter
    filtered_res = await store.get_recent_completed(
        _DESTINATION, limit=5, before=base_time + timedelta(minutes=2)
    )
    assert is_ok(filtered_res)
    assert len(filtered_res.value) == 1
    assert filtered_res.value[0].source_message_id == "ep_1"


@pytest.mark.anyio
async def test_times_episode_store_persists_work_intent_links(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Persist the structured commitment and its idempotent work link."""
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    intent = TimesWorkIntent(
        intent_id="episode-1:0",
        character_name="Lilia",
        objective="公式資料を確認する",
        context="Timesで合意した",
        success_criteria=("URLを記録する",),
    )
    plan = TimesEpisodePlan(
        source_message_id="episode-1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Lilia", content="調べてくる。"),),
        status="COMPLETED",
        next_post_index=1,
        owner_id="2",
        work_intents=(intent,),
    )

    assert is_ok(await store.save(plan))
    fetched = (await store.get("episode-1")).unwrap()
    assert fetched is not None
    assert fetched.owner_id == "2"
    assert fetched.work_intents == (intent,)

    linked = replace(plan, work_intents=(replace(intent, work_id="100"),))
    assert is_ok(await store.save(linked))
    updated = (await store.get("episode-1")).unwrap()
    assert updated is not None
    assert updated.work_intents[0].work_id == "100"


@pytest.mark.anyio
async def test_failed_episode_can_be_reopened_with_same_generated_posts(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Recovery may clear a failure without changing an already generated plan."""
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    failed = TimesEpisodePlan(
        source_message_id="failed-episode",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Dorothy", content="再送"),),
        status="FAILED",
        failure="temporary delivery failure",
        next_post_index=0,
    )
    assert is_ok(await store.save(failed))

    reopened = replace(failed, failure=None, status="PENDING")
    assert is_ok(await store.save(reopened))
    fetched = (await store.get("failed-episode")).unwrap()
    assert fetched is not None and fetched.failure is None


@pytest.mark.anyio
async def test_completed_work_query_is_not_limited_to_recent_twenty(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Restart recovery must find an old unlinked commitment as well as recent ones."""
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    for index in range(21):
        intent = TimesWorkIntent(
            intent_id=f"episode-{index}:0",
            character_name="Lilia",
            objective="調査",
        )
        plan = TimesEpisodePlan(
            source_message_id=f"episode-{index}",
            guild_id="456",
            channel_id="123",
            delivery_channel_id="999",
            posts=(TimesPost(character_name="Lilia", content="調べてくる。"),),
            status="COMPLETED",
            next_post_index=1,
            work_intents=(intent,),
            created_at=datetime(2026, 9, 12, 10, index, tzinfo=UTC),
        )
        assert is_ok(await store.save(plan))

    result = await store.get_completed_with_work(_DESTINATION)

    assert is_ok(result)
    assert len(result.value) == 21


@pytest.mark.anyio
async def test_completed_history_is_filtered_by_times_destination_before_limiting(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    store = SQLAlchemyTimesEpisodeStore(session_factory)
    plan = TimesEpisodePlan(
        source_message_id="current_times_destination",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(TimesPost(character_name="Dorothy", content="Current Times memory"),),
        status="COMPLETED",
        next_post_index=1,
        created_at=datetime(2026, 9, 12, 10, 0, tzinfo=UTC),
    )
    assert is_ok(await store.save(plan))
    for index, (guild_id, channel_id) in enumerate((("456", "777"), ("888", "999"))):
        other = replace(
            plan,
            source_message_id=f"other_times_destination_{index}",
            guild_id=guild_id,
            delivery_channel_id=channel_id,
            created_at=datetime(2026, 9, 12, 11, index, tzinfo=UTC),
        )
        assert is_ok(await store.save(other))

    result = await store.get_recent_completed(_DESTINATION, limit=1)

    assert is_ok(result)
    assert [episode.source_message_id for episode in result.value] == [
        "current_times_destination"
    ]
