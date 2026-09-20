"""Regression scenarios discovered by comparing the full design with the runtime."""

from typing import cast

import pytest

from app.contracts.messages.collective import (
    Character,
    Decision,
    MemoryCandidate,
    MemorySource,
    WorkResult,
)
from app.usecases.collective.lifecycle import add_event, enqueue
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import CodexDouble, ConversationDouble
from tests.collective.test_runtime import start_change


@pytest.mark.anyio
async def test_silent_reflections_do_not_wake_peers(collective: Collective) -> None:
    collective.schedule(1)
    assert await collective.conversation_step(1)
    assert await collective.conversation_step(2)
    assert not await collective.conversation_step(3)
    state = collective.store.read()
    assert len(state.turns) == 2
    assert not state.speeches
    assert all(turn.status == "applied" for turn in state.turns.values())


@pytest.mark.anyio
async def test_audit_records_stay_saved_without_becoming_conversation_history(
    collective: Collective,
) -> None:
    with collective.store.transaction() as state:
        for kind in ("decision", "attention", "input_check"):
            add_event(state, kind, kind, "alice", "times", "shared", "OLD_SILENCE", 0)
        add_event(
            state, "spoken", "speech", "alice", "times", "shared", "REAL_WORDS", 0
        )
        add_event(
            state,
            "observed",
            "work_result",
            "alice",
            "times",
            "shared",
            "OBSERVED_RESULT",
            0,
        )
    collective.receive("1", "今の話題", "times", 1, "alice")
    await collective.conversation_step(1)
    context = cast(ConversationDouble, collective.conversation).contexts[0]
    assert "OLD_SILENCE" not in context.model_dump_json()
    assert "REAL_WORDS" in context.model_dump_json()
    assert "OBSERVED_RESULT" in context.model_dump_json()
    assert collective.store.read().events["decision"].content == "OLD_SILENCE"


@pytest.mark.anyio
async def test_three_person_times_continues_past_one_silent_candidate(
    collective: Collective,
) -> None:
    collective.characters["charlie"] = Character(
        id="charlie",
        name="Charlie",
        persona="Charlie personality",
        public_profile="Charlie profile",
    )
    collective.settings.max_round = 4
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [
        Decision(speech="比較が役立ちそう。", consult="bob"),
        Decision(),
        Decision(change=start_change()),
        Decision(),
    ]
    collective.receive("1", "候補について", "times", 1, "alice")
    for now in range(1, 6):
        await collective.conversation_step(now)
    assert [context.character.id for context in conversation.contexts] == [
        "alice",
        "bob",
        "charlie",
    ]
    assert next(iter(collective.store.read().activities.values())).owner == "charlie"
    assert len(collective.store.read().speeches) == 1
    assert "silence" not in conversation.contexts[-1].trigger.content


@pytest.mark.anyio
@pytest.mark.parametrize("speech", [None, "Bobにも確認します。"])
async def test_master_conversation_can_consult_an_actual_peer(
    collective: Collective, speech: str | None
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [
        Decision(speech=speech, consult="bob"),
        Decision(speech="確認しました。"),
    ]
    collective.receive("1", "違う観点でも確認して", "master", 1, "alice")
    await collective.conversation_step(1)
    assert await collective.conversation_step(2)
    assert [context.character.id for context in conversation.contexts] == [
        "alice",
        "bob",
    ]


@pytest.mark.anyio
async def test_reflection_work_input_does_not_include_peer_private_results(
    collective: Collective,
) -> None:
    with collective.store.transaction() as state:
        add_event(
            state,
            "bob-reflection",
            "work_result",
            "bob",
            "times",
            "old",
            "BOB_PRIVATE_RESULT",
            0,
        )
    collective.settings.reflection_lane = "work"
    collective.schedule(1)
    worker = cast(CodexDouble, collective.codex)
    worker.results = [WorkResult(summary="No action", action="propose")]
    await collective.work_step(1)
    context = worker.contexts[0]
    assert context.context.character.id == "alice"
    assert "BOB_PRIVATE_RESULT" not in context.model_dump_json()


@pytest.mark.anyio
async def test_memory_pass_marks_supplied_unneeded_sources_after_updating_one_note(
    collective: Collective,
) -> None:
    with collective.store.transaction() as state:
        for source in ("one", "omitted", "two"):
            add_event(state, source, "message", "master", "master", source, source, 1)
            state.memory_sources[f"alice/{source}"] = MemorySource(
                owner="alice", event_id=source
            )
        enqueue(state, "alice", state.events["one"], "memory")
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.counts = [901, 100]
    conversation.decisions = [
        Decision(
            memories=[
                MemoryCandidate(
                    owner="alice",
                    note_id="experience",
                    section="timeline",
                    kind="interpretation",
                    content="Useful experience",
                    sources=["one"],
                )
            ]
        )
    ]
    await collective.conversation_step(2)
    sources = collective.store.read().memory_sources
    assert sources["alice/one"].status == "extracted"
    assert sources["alice/two"].status == "extracted"
    assert sources["alice/omitted"].status == "pending"


@pytest.mark.anyio
async def test_one_source_can_produce_two_notes_without_duplicate_extraction(
    collective: Collective,
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    candidates = [
        MemoryCandidate(
            owner="alice",
            note_id=name,
            section="timeline",
            kind="interpretation",
            content=name,
            sources=["discord:1"],
        )
        for name in ("first", "second")
    ]
    conversation.decisions = [
        Decision(memories=candidates),
        Decision(memories=candidates),
    ]
    collective.receive("1", "Two distinct lessons", "master", 1, "alice")
    await collective.conversation_step(1)
    assert set(collective.store.read().memories) == {"alice/first", "alice/second"}
    collective.receive("2", "Recall the earlier lessons", "master", 2, "alice")
    await collective.conversation_step(2)
    state = collective.store.read()
    assert all(note.version == 1 for note in state.memories.values())
    assert not any(turn.purpose == "memory" for turn in state.turns.values())
