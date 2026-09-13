"""Times-to-Codex dispatch and reviewed follow-up tests."""

from unittest.mock import AsyncMock

import pytest
from flow_res import Ok

from app.contracts.messages.character_work import CharacterWork
from app.contracts.messages.times_message import (
    TimesEpisodePlan,
    TimesWorkIntent,
)
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.contracts.ports.times_publisher import ITimesPublisher
from app.domain.characters import CharacterRoster
from app.presentation.bot.times_work_dispatcher import TimesWorkDispatcher


def _roster() -> CharacterRoster:
    from app.application.character_settings import load_ai_maid_definitions

    return load_ai_maid_definitions()


def _intent() -> TimesWorkIntent:
    return TimesWorkIntent(
        intent_id="episode-1:0",
        character_name="Lilia",
        objective="公式資料を確認する",
        context="相談で必要になった",
        success_criteria=("URLを記録する",),
    )


def _plan(intent: TimesWorkIntent) -> TimesEpisodePlan:
    return TimesEpisodePlan(
        source_message_id="episode-1",
        guild_id="456",
        channel_id="123",
        delivery_channel_id="999",
        posts=(),
        status="COMPLETED",
        owner_id="2",
        work_intents=(intent,),
    )


@pytest.mark.anyio
async def test_dispatch_starts_intent_and_persists_work_link() -> None:
    store = AsyncMock(spec=ITimesEpisodeStore)
    store.save.return_value = Ok(None)
    publisher = AsyncMock(spec=ITimesPublisher)
    task = CharacterWork(
        "100",
        "456",
        "777",
        "2",
        "lilia",
        "調査",
        "100",
        origin="times",
        origin_key="episode-1:0",
    )
    starter = AsyncMock(return_value=task)
    dispatcher = TimesWorkDispatcher(
        store,
        publisher,
        _roster(),
        "999",
        starter,
    )

    await dispatcher.dispatch(_plan(_intent()))

    starter.assert_awaited_once()
    saved = store.save.await_args.args[0]
    assert saved.work_intents[0].work_id == "100"
    publisher.deliver.assert_not_awaited()


@pytest.mark.anyio
async def test_retry_pending_scans_all_completed_episodes_after_capacity_frees() -> (
    None
):
    store = AsyncMock(spec=ITimesEpisodeStore)
    store.get_completed_with_work.return_value = Ok([_plan(_intent())])
    store.save.return_value = Ok(None)
    publisher = AsyncMock(spec=ITimesPublisher)
    task = CharacterWork(
        "100",
        "456",
        "777",
        "2",
        "lilia",
        "調査",
        "100",
        origin="times",
        origin_key="episode-1:0",
    )
    starter = AsyncMock(return_value=task)
    dispatcher = TimesWorkDispatcher(
        store,
        publisher,
        _roster(),
        "999",
        starter,
    )

    await dispatcher.retry_pending(task)

    store.get_completed_with_work.assert_awaited_once()
    starter.assert_awaited_once()


@pytest.mark.anyio
async def test_reviewed_times_work_is_published_as_one_natural_followup() -> None:
    store = AsyncMock(spec=ITimesEpisodeStore)
    store.get.return_value = Ok(None)
    store.save.return_value = Ok(None)
    publisher = AsyncMock(spec=ITimesPublisher)
    dispatcher = TimesWorkDispatcher(
        store,
        publisher,
        _roster(),
        "999",
        AsyncMock(),
    )
    task = CharacterWork(
        "100",
        "456",
        "777",
        "2",
        "lilia",
        "調査",
        "100",
        origin="times",
        origin_key="episode-1:0",
        origin_channel_id="999",
        times_episode_id="episode-1",
        review="公式資料を確認しました。",
    )

    await dispatcher.publish_completion(task)

    saved = store.save.await_args.args[0]
    assert saved.source_message_id == "work:100"
    assert saved.work_intents == ()
    assert saved.posts[0].character_name == "Lilia"
    assert saved.posts[0].content == "公式資料を確認しました。"
    publisher.deliver.assert_awaited_once_with(saved)


@pytest.mark.anyio
async def test_unreviewed_times_work_does_not_create_followup() -> None:
    store = AsyncMock(spec=ITimesEpisodeStore)
    publisher = AsyncMock(spec=ITimesPublisher)
    dispatcher = TimesWorkDispatcher(
        store,
        publisher,
        _roster(),
        "999",
        AsyncMock(),
    )
    task = CharacterWork(
        "100",
        "456",
        "777",
        "2",
        "lilia",
        "調査",
        "100",
        origin="times",
    )

    await dispatcher.publish_completion(task)

    store.get.assert_not_awaited()
    publisher.deliver.assert_not_awaited()
