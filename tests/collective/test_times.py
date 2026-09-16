"""Bound automatic public conversation without stopping private initiative."""

from typing import cast

import pytest

from app.contracts.messages.collective import Decision, MemoryCandidate, Report
from app.infrastructure.collective.store import SQLiteCollectiveStore
from app.usecases.collective.lifecycle import save_speech
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import ConversationDouble
from tests.collective.test_runtime import start_change


@pytest.mark.anyio
async def test_ten_overdue_reflections_share_one_three_turn_conversation(
    collective: Collective,
) -> None:
    template = collective.characters["alice"]
    collective.characters = {
        str(index): template.model_copy(update={"id": str(index)})
        for index in range(10)
    }
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [Decision(speech="A new point") for _ in range(12)]
    collective.schedule(1)
    for _ in range(12):
        assert await collective.conversation_step(2)
    assert not await collective.conversation_step(2)
    state = collective.store.read()
    assert len(state.speeches) == 3
    assert len({speech.origin for speech in state.speeches.values()}) == 1
    reflections = [
        turn for turn in state.turns.values() if turn.purpose == "reflection"
    ]
    assert len(reflections) == 10
    assert all(turn.status == "applied" for turn in reflections)
    assert [context.times_speech_allowed for context in conversation.contexts] == [
        True,
        *([False] * 9),
        True,
        True,
    ]


@pytest.mark.anyio
async def test_cooldown_survives_restart_and_expires_after_last_speech(
    collective: Collective,
) -> None:
    collective.settings.times_interval_seconds = 100
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [
        Decision(speech="First"),
        Decision(),
        Decision(speech="Reply"),
    ]
    collective.schedule(1)
    for _ in range(4):
        await collective.conversation_step(2)
    assert len(collective.store.read().speeches) == 2
    collective.store = SQLiteCollectiveStore(collective.root)
    collective.schedule(101)
    conversation.decisions = [Decision(speech="Too early"), Decision(speech="Next")]
    await collective.conversation_step(101.999)
    assert len(collective.store.read().speeches) == 2
    await collective.conversation_step(102)
    assert len(collective.store.read().speeches) == 3
    assert not conversation.contexts[-2].times_speech_allowed
    assert conversation.contexts[-1].times_speech_allowed


@pytest.mark.anyio
async def test_silent_reflection_does_not_reserve_public_conversation(
    collective: Collective,
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [Decision(), Decision(speech="A different view")]
    collective.schedule(1)
    await collective.conversation_step(2)
    await collective.conversation_step(2)
    assert all(context.times_speech_allowed for context in conversation.contexts)
    assert [
        speech.character_id for speech in collective.store.read().speeches.values()
    ] == ["bob"]


@pytest.mark.parametrize("speech", [None, "A queued promise"])
def test_apply_rechecks_saved_output_but_keeps_memory_and_work(
    collective: Collective,
    speech: str | None,
) -> None:
    collective.schedule(1)
    alice = collective._claim("conversation", 2)
    assert alice is not None and alice.context is not None
    assert alice.context.times_speech_allowed
    decision = Decision(
        speech=speech,
        consult="bob",
        change=start_change(),
        inspect=True,
        memories=[
            MemoryCandidate(
                owner="alice",
                note_id="observation",
                section="timeline",
                kind="interpretation",
                content="Considered a comparison",
                sources=[alice.trigger_id],
            )
        ],
    )
    collective._save_output(alice, decision.model_dump_json(), 2)
    with collective.store.transaction() as state:
        bob = next(turn for turn in state.turns.values() if turn.character_id == "bob")
        save_speech(
            state, bob, collective.characters, collective.settings, 3, body="First"
        )
    collective._apply(alice.id, 4)
    state = collective.store.read()
    assert state.turns[alice.id].status == "applied"
    assert alice.id not in state.speeches
    assert next(iter(state.activities.values())).owner == "alice"
    assert any(memory.owner == "alice" for memory in state.memories.values())
    assert any(
        turn.origin == alice.origin and turn.lane == "work"
        for turn in state.turns.values()
    )
    assert not any(
        turn.origin == alice.origin and turn.purpose == "conversation"
        for turn in state.turns.values()
    )


@pytest.mark.anyio
async def test_cooldown_does_not_block_master_replies_or_work_reports(
    collective: Collective,
) -> None:
    collective.settings.max_round = 1
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [Decision(speech="Automatic"), Decision()]
    collective.schedule(1)
    await collective.conversation_step(2)
    await collective.conversation_step(2)
    for scope in ("master", "times"):
        conversation.decisions.append(Decision(speech="Reply to master"))
        collective.receive(scope, "Actual request", scope, 3, "alice")
        await collective.conversation_step(3)
        assert conversation.contexts[-1].times_speech_allowed
    with collective.store.transaction() as state:
        bob = next(turn for turn in state.turns.values() if turn.character_id == "bob")
        save_speech(
            state,
            bob,
            collective.characters,
            collective.settings,
            4,
            report=Report(achieved=["Actual work"]),
        )
    assert len(collective.store.read().speeches) == 4
    assert collective.store.read().speeches[bob.id].scope == "master"


@pytest.mark.anyio
async def test_lowered_limit_blocks_already_queued_continuation(
    collective: Collective,
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [
        Decision(speech="First"),
        Decision(),
        Decision(speech="Extra"),
    ]
    collective.schedule(1)
    await collective.conversation_step(2)
    await collective.conversation_step(2)
    collective.settings.max_round = 1
    collective.store = SQLiteCollectiveStore(collective.root)
    await collective.conversation_step(3)
    assert len(collective.store.read().speeches) == 1
    assert not conversation.contexts[-1].times_speech_allowed
    assert not await collective.conversation_step(3)
