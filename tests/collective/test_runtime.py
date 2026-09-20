"""Acceptance paths A1-A5, A9-A12 across real transactions and restart boundaries."""

from typing import cast

import pytest

from app.contracts.messages.collective import (
    ActivityChange,
    Decision,
    Memory,
    MemoryCandidate,
    Report,
    WorkResult,
)
from app.contracts.ports.collective import InputTooLarge
from app.usecases.collective.lifecycle import add_event
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import CodexDouble, ConversationDouble


def start_change() -> ActivityChange:
    """Define a concrete bounded support objective."""
    return ActivityChange(
        action="start",
        objective="Compare A and B",
        value="Reduce decision effort",
        target="A/B",
        criteria=["cost", "maintenance"],
        next_step="Read official specifications",
    )


async def start_activity(collective: Collective) -> str:
    """Start work from ordinary conversation."""
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions.append(
        Decision(speech="比較しておきます。", change=start_change())
    )
    collective.receive("1", "AとB、どちらがよいかな", "master", 1, "alice")
    await collective.conversation_step(1)
    return next(iter(collective.store.read().activities))


def finished() -> WorkResult:
    """Provide criterion-specific evidence with useful reporting facts."""
    return WorkResult(
        summary="Compared official specifications",
        action="done",
        evidence={
            "cost": "A costs 10, B costs 20",
            "maintenance": "B includes updates",
        },
        report=Report(
            achieved=["comparison"],
            findings=["A is cheaper", "B includes maintenance"],
            evidence=["official specifications"],
            uncertainty=["actual operation untested"],
        ),
    )


@pytest.mark.anyio
async def test_a1_reflection_without_activity_or_human(collective: Collective) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions.append(Decision(change=start_change()))
    collective.schedule(1)
    collective.schedule(2)
    assert len(collective.store.read().turns) == 2
    await collective.conversation_step(2)
    assert len(collective.store.read().activities) == 1
    assert not any(e.actor == "master" for e in collective.store.read().events.values())
    collective.schedule(3)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(finished())
    await collective.work_step(3)
    assert len(codex.contexts) == 1
    assert next(iter(collective.store.read().activities.values())).status == "done"


@pytest.mark.anyio
async def test_a1_codex_reflection_proposes_before_writing(
    collective: Collective,
) -> None:
    collective.settings.reflection_lane = "work"
    collective.schedule(1)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(
        WorkResult(
            summary="Preparation would help", action="propose", proposal=start_change()
        )
    )
    await collective.work_step(1)
    assert codex.contexts[0].activity is None
    assert next(iter(collective.store.read().activities.values())).status == "ready"


@pytest.mark.anyio
async def test_a2_times_each_person_decides_separately(collective: Collective) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions.extend(
        [
            Decision(speech="この比較、必要そう。", consult="bob"),
            Decision(speech="私が確認しておく。", change=start_change()),
            Decision(),
        ]
    )
    collective.receive("1", "最近の比較について", "times", 1, "alice")
    for now in range(1, 5):
        await collective.conversation_step(now)
    contexts = conversation.contexts
    assert [c.character.id for c in contexts] == ["alice", "bob", "alice"]
    assert all(c.scope == "times" for c in contexts)
    assert next(iter(collective.store.read().activities.values())).owner == "bob"
    assert len(collective.store.read().speeches) == 2
    assert not collective.receive("1", "duplicate", "times", 5)


@pytest.mark.anyio
async def test_a3_greeting_correction_stop_and_late_result(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    work = collective._claim("work", 2)
    assert work is not None
    before = collective.store.read().activities[activity_id].version
    conversation = cast(ConversationDouble, collective.conversation)
    collective.receive("2", "おはよう", "master", 3, "alice")
    await collective.conversation_step(3)
    # Reflection turns precede the greeting and cannot mutate activity versions.
    while await collective.conversation_step(3):
        pass
    assert collective.store.read().activities[activity_id].version == before
    conversation.decisions.append(
        Decision(
            change=ActivityChange(
                action="update",
                activity_id=activity_id,
                expected_version=before,
                reason="Include support cost",
                next_step="Compare total support cost",
            )
        )
    )
    collective.receive("3", "保守費用も含めて", "master", 4, "alice")
    await collective.conversation_step(4)
    assert cast(CodexDouble, collective.codex).interrupted == [work.id]
    latest = collective.store.read().activities[activity_id]
    conversation.decisions.append(
        Decision(
            speech="止めておきます。",
            change=ActivityChange(
                action="stop",
                activity_id=activity_id,
                expected_version=latest.version,
                reason="Stop this comparison",
            ),
        )
    )
    collective.receive("4", "その比較は中止して", "master", 5, "alice")
    await collective.conversation_step(5)
    collective._save_output(work, finished().model_dump_json(), 6)
    collective._apply(work.id, 6)
    state = collective.store.read()
    assert state.activities[activity_id].status == "stopped"
    assert f"result:{work.id}" in state.events
    collective.schedule(6)
    assert not any(
        t.status == "pending" and t.activity_id == activity_id
        for t in collective.store.read().turns.values()
    )


@pytest.mark.anyio
async def test_a4_restart_applies_saved_work_without_reexecution(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    work = collective._claim("work", 2)
    assert work is not None
    collective._save_output(work, finished().model_dump_json(), 3)
    await collective.recover(4)
    assert collective.store.read().activities[activity_id].status == "done"
    assert not cast(CodexDouble, collective.codex).contexts
    await collective.recover(5)
    assert (
        len([s for s in collective.store.read().speeches.values() if s.body is None])
        == 1
    )


@pytest.mark.anyio
async def test_a4_unknown_execution_requires_exit_confirmation(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    work = collective._claim("work", 2)
    assert work is not None
    codex = cast(CodexDouble, collective.codex)
    codex.confirm_exit = False
    await collective.recover(3)
    assert collective.store.read().turns[work.id].status == "running"
    assert not await collective.work_step(3)
    codex.confirm_exit = True
    await collective.recover(4)
    assert collective.store.read().activities[activity_id].status == "ready"
    codex.results.append(finished())
    await collective.work_step(4)
    assert codex.contexts[0].recovery


@pytest.mark.anyio
async def test_a4_sleeping_restores_due_condition(collective: Collective) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(
        WorkResult(
            summary="Await published results",
            action="sleep",
            reason="Results due later",
            wake_at=50,
        )
    )
    await collective.work_step(2)
    collective.schedule(49)
    assert collective.store.read().activities[activity_id].status == "sleeping"
    collective.schedule(50)
    assert collective.store.read().activities[activity_id].status == "ready"


@pytest.mark.anyio
async def test_a5_corrected_owned_memory_in_conversation_and_work(
    collective: Collective,
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    for number, content in [(1, "old"), (2, "corrected")]:
        conversation.decisions.append(
            Decision(
                memories=[
                    MemoryCandidate(
                        owner="master",
                        note_id="preference",
                        kind="fact",
                        section="profile",
                        content=content,
                        sources=[f"discord:{number}"],
                        expected_version=number - 1,
                    )
                ]
            )
        )
        collective.receive(str(number), content, "master", number, "alice")
        await collective.conversation_step(number)
    with collective.store.transaction() as state:
        state.memories["bob/private"] = Memory(
            owner="bob",
            note_id="private",
            section="timeline",
            kind="interpretation",
            content="Bob secret",
            sources=["discord:1"],
        )
    conversation.decisions.append(Decision(change=start_change()))
    collective.receive("3", "進めて", "master", 3, "alice")
    await collective.conversation_step(3)
    context = conversation.contexts[-1].model_dump_json()
    assert "corrected" in context and "Bob secret" not in context
    collective.schedule(4)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(finished())
    await collective.work_step(4)
    projection = codex.contexts[0].workspace / "master" / "profile-preference.md"
    assert "corrected" in projection.read_text()
    assert collective.store.read().memories["master/preference"].version == 2


@pytest.mark.anyio
async def test_a5_memory_conflict_does_not_lose_completed_work(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    work = collective._claim("work", 2)
    assert work is not None
    candidate = MemoryCandidate(
        owner="alice",
        note_id="experience",
        kind="interpretation",
        section="timeline",
        content="new",
        sources=[f"result:{work.id}"],
    )
    result = finished().model_copy(update={"memories": [candidate]})
    with collective.store.transaction() as state:
        state.memories[candidate.key] = Memory(
            owner="alice",
            note_id="experience",
            kind="interpretation",
            section="timeline",
            content="concurrent",
            sources=["discord:1"],
        )
    collective._save_output(work, result.model_dump_json(), 3)
    collective._apply(work.id, 3)
    state = collective.store.read()
    assert state.activities[activity_id].status == "done"
    assert state.memories[candidate.key].content == "concurrent"
    assert any(
        t.purpose == "memory" and t.status == "pending" for t in state.turns.values()
    )


@pytest.mark.anyio
async def test_a10_generation_failure_does_not_repeat_work_or_send_raw_result(
    collective: Collective,
) -> None:
    await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(finished())
    await collective.work_step(2)
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.render_error = RuntimeError("offline")
    for _ in range(5):
        await collective.conversation_step(3)
    assert any(
        s.status == "unrendered" for s in collective.store.read().speeches.values()
    )
    conversation.render_error = None
    await collective.conversation_step(10)
    assert len(codex.contexts) == 1
    assert any(
        s.body and "実運用は未確認" in s.body
        for s in collective.store.read().speeches.values()
    )


@pytest.mark.anyio
@pytest.mark.parametrize("tokens", [899, 900, 901])
async def test_a12_capacity_before_at_and_above_budget(
    collective: Collective, tokens: int
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.counts = [tokens, 100]
    with collective.store.transaction() as state:
        add_event(
            state,
            "old",
            "message",
            "master",
            "times",
            "old",
            "Old unrelated conversation",
            0,
        )
    collective.receive("1", "現在の依頼", "master", 1, "alice")
    await collective.conversation_step(1)
    turn = next(iter(collective.store.read().turns.values()))
    assert turn.status == "applied"
    assert bool(conversation.contexts[-1].omissions) == (tokens > 900)
    assert turn.input_attempts[0].remaining == 900 - tokens
    assert "old" in collective.store.read().events


@pytest.mark.anyio
async def test_a12_api_overflow_reduces_before_retry(collective: Collective) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions = [InputTooLarge(), Decision(speech="了解しました。")]
    with collective.store.transaction() as state:
        add_event(state, "old", "message", "master", "times", "old", "Unrelated", 0)
    collective.receive("1", "停止対象はこの比較", "master", 1, "alice")
    await collective.conversation_step(1)
    assert len(conversation.contexts) == 2
    assert len(conversation.contexts[0].items) > len(conversation.contexts[1].items)
    assert conversation.contexts[1].trigger.content == "停止対象はこの比較"


@pytest.mark.anyio
async def test_a12_required_overflow_holds_once(collective: Collective) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.counts = [901]
    collective.receive("1", "必須の指示", "master", 1, "alice")
    await collective.conversation_step(1)
    assert next(iter(collective.store.read().turns.values())).status == "held"
    assert not await collective.conversation_step(100)
    assert not conversation.contexts
