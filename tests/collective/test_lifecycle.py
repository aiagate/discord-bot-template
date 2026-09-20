"""Reject invalid transitions and preserve facts across ownership and version races."""

from typing import cast

import pytest

from app.contracts.messages.collective import (
    ActivityChange,
    ContextItem,
    Decision,
    InputAttempt,
    MemoryCandidate,
    Report,
    Turn,
    WorkResult,
)
from app.usecases.collective.lifecycle import add_event
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import CodexDouble, ConversationDouble
from tests.collective.test_runtime import finished, start_activity, start_change


@pytest.mark.anyio
@pytest.mark.parametrize("suggested_id", ["existing", "model-proposed-name"])
async def test_new_activity_keeps_server_identity(
    collective: Collective, suggested_id: str
) -> None:
    existing_id = await start_activity(collective)
    existing = collective.store.read().activities[existing_id]
    requested_id = existing_id if suggested_id == "existing" else suggested_id
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions.append(
        Decision(
            speech="別の比較も確認します。",
            change=start_change().model_copy(
                update={
                    "activity_id": requested_id,
                    "objective": "Compare C and D",
                    "target": "C/D",
                }
            ),
        )
    )
    collective.receive("2", "CとDも比較して", "master", 2, "alice")
    await collective.conversation_step(2)
    state = collective.store.read()
    turn = next(t for t in state.turns.values() if t.trigger_id == "discord:2")
    assert turn.status == "applied"
    assert state.activities[existing_id] == existing
    created = next(a for a in state.activities.values() if a.id != existing_id)
    assert created.id != requested_id
    assert created.objective == "Compare C and D"
    assert state.speeches[turn.id].body == "別の比較も確認します。"
    collective._apply(turn.id, 3)
    assert len(collective.store.read().activities) == 2


@pytest.mark.anyio
@pytest.mark.parametrize(
    "result,status",
    [
        (
            WorkResult(
                summary="More needed", action="continue", next_step="Check again"
            ),
            "ready",
        ),
        (
            WorkResult(
                summary="Need an answer",
                action="ask",
                report=Report(question="Which location?"),
            ),
            "waiting",
        ),
        (
            WorkResult(
                summary="Cannot access target",
                action="blocked",
                reason="Access missing",
                next_step="Wait for access",
            ),
            "blocked",
        ),
        (
            WorkResult(
                summary="Need another perspective",
                action="handoff",
                reason="Check operating cost",
                recipient="bob",
                next_step="Check support costs",
                remaining=["operating cost"],
            ),
            "ready",
        ),
    ],
)
async def test_work_continuations(
    collective: Collective, result: WorkResult, status: str
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(result)
    await collective.work_step(2)
    activity = collective.store.read().activities[activity_id]
    assert activity.status == status
    if result.action == "handoff":
        assert activity.owner == "bob"
        assert activity.remaining == ["operating cost"]
    if result.action == "ask":
        assert activity.question == "Which location?"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "result",
    [
        WorkResult(
            summary="Incomplete",
            action="done",
            evidence={"cost": "known"},
            report=Report(),
        ),
        WorkResult(summary="No question", action="ask"),
        WorkResult(summary="No time", action="sleep"),
        WorkResult(summary="No next step", action="continue"),
        WorkResult(summary="No recipient", action="handoff", next_step="Check"),
        WorkResult(summary="No reason", action="blocked"),
        WorkResult(summary="Wrong operation", action="propose"),
    ],
)
async def test_invalid_work_is_held_without_repeating_external_operations(
    collective: Collective, result: WorkResult
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    cast(CodexDouble, collective.codex).results.append(result)
    await collective.work_step(2)
    state = collective.store.read()
    turn = next(t for t in state.turns.values() if t.purpose == "work")
    assert turn.status == "held"
    assert state.activities[activity_id].status == "blocked"
    assert turn.output is not None
    assert not await collective.work_step(100)


@pytest.mark.anyio
@pytest.mark.parametrize("complete", [True, False])
async def test_additional_evidence_preserves_required_completion_criteria(
    collective: Collective, complete: bool
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    result = finished()
    result.evidence["quality checks"] = "Build and tests passed"
    if not complete:
        del result.evidence["maintenance"]
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(result)
    await collective.work_step(2)
    state = collective.store.read()
    activity = state.activities[activity_id]
    turn = next(t for t in state.turns.values() if t.purpose == "work")
    assert activity.status == ("done" if complete else "blocked")
    assert turn.status == ("applied" if complete else "held")
    if complete:
        assert activity.evidence == result.evidence
        assert state.speeches[turn.id].report == result.report
    assert not await collective.work_step(100)
    assert len(codex.contexts) == 1


@pytest.mark.anyio
async def test_stale_conversation_rejudges_original_input(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.receive("2", "止めて", "master", 2, "alice")
    turn = collective._claim("conversation", 2)
    assert turn is not None
    output = Decision(
        speech="停止しました。",
        change=ActivityChange(
            action="stop", activity_id=activity_id, expected_version=1, reason="Stop"
        ),
    )
    await collective.stop(activity_id, "Newer stop", 3)
    collective._save_output(turn, output.model_dump_json(), 4)
    from app.usecases.collective.lifecycle import StaleDecision

    with pytest.raises(StaleDecision) as error:
        collective._apply(turn.id, 4)
    collective._fail(turn.id, error.value, 4)
    saved = collective.store.read().turns[turn.id]
    assert saved.status == "retry" and saved.output is None
    await collective.conversation_step(10)
    assert (
        cast(ConversationDouble, collective.conversation).contexts[-1].trigger.content
        == "止めて"
    )


@pytest.mark.anyio
async def test_peer_private_records_never_enter_context(collective: Collective) -> None:
    with collective.store.transaction() as state:
        add_event(
            state,
            "secret",
            "work_result",
            "bob",
            "times",
            "secret",
            "BOB_PRIVATE_EXPERIENCE",
            0,
        )
        add_event(
            state, "public", "speech", "bob", "times", "public", "Shared finding", 0
        )
    collective.receive("1", "Hello", "master", 1, "alice")
    turn = collective._claim("conversation", 1)
    assert turn is not None and turn.context is not None
    assert "BOB_PRIVATE_EXPERIENCE" not in turn.context.model_dump_json()
    assert "Shared finding" in turn.context.model_dump_json()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "owner,kind,sources",
    [
        ("bob", "interpretation", ["discord:1"]),
        ("master", "interpretation", ["discord:1"]),
        ("alice", "fact", ["nonexistent"]),
    ],
)
async def test_memory_ownership_and_sources_reject_invalid_candidates(
    collective: Collective, owner: str, kind: str, sources: list[str]
) -> None:
    conversation = cast(ConversationDouble, collective.conversation)
    candidate = MemoryCandidate.model_validate(
        {
            "owner": owner,
            "note_id": "note",
            "kind": kind,
            "section": "timeline",
            "content": "claim",
            "sources": sources,
        }
    )
    conversation.decisions.append(
        Decision(memories=[candidate], speech="保存しました。")
    )
    collective.receive("1", "Hello", "master", 1, "alice")
    await collective.conversation_step(1)
    state = collective.store.read()
    assert not state.memories and not state.speeches
    assert next(iter(state.turns.values())).status == "held"


@pytest.mark.anyio
async def test_file_result_recovered_before_application_database_checkpoint(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    turn = collective._claim("work", 2)
    assert turn is not None
    codex = cast(CodexDouble, collective.codex)
    codex.saved_output = finished().model_dump_json()
    await collective.recover(3)
    assert collective.store.read().activities[activity_id].status == "done"
    assert not codex.contexts


@pytest.mark.anyio
async def test_work_failure_retries_with_state_inspection(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    codex.results = [RuntimeError("connection lost"), finished()]
    await collective.work_step(2)
    assert collective.store.read().activities[activity_id].status == "ready"
    await collective.work_step(4)
    assert codex.contexts[1].recovery
    assert collective.store.read().activities[activity_id].status == "done"


@pytest.mark.anyio
async def test_unconfirmed_work_failure_retains_lane(collective: Collective) -> None:
    await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    codex.confirm_exit = False
    codex.results = [RuntimeError("connection lost")]
    await collective.work_step(2)
    assert not await collective.work_step(10)
    assert any(
        t.error.startswith("Process termination")
        for t in collective.store.read().turns.values()
    )


@pytest.mark.anyio
async def test_startup_records_counts_without_starting_model_work(
    collective: Collective,
) -> None:
    await collective.validate_inputs(1)
    state = collective.store.read()
    assert not state.turns and not state.activities
    assert len(state.events) == len(collective.characters)
    assert all(
        InputAttempt.model_validate_json(event.content).remaining == 800
        for event in state.events.values()
    )
    assert not cast(ConversationDouble, collective.conversation).contexts


@pytest.mark.anyio
async def test_explicit_resume_renews_exhausted_work_budget(
    collective: Collective,
) -> None:
    activity_id = await start_activity(collective)
    with collective.store.transaction() as state:
        activity = state.activities[activity_id]
        activity.runs = collective.settings.max_activity_runs
        activity.status = "blocked"
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions.append(
        Decision(
            change=ActivityChange(
                action="resume",
                activity_id=activity_id,
                expected_version=1,
                reason="Master explicitly resumed the comparison",
            )
        )
    )
    collective.receive("2", "この比較を再開して", "master", 2, "alice")
    await collective.conversation_step(2)
    collective.schedule(3)
    activity = collective.store.read().activities[activity_id]
    assert activity.status == "ready" and activity.runs == 0


@pytest.mark.anyio
async def test_correction_and_original_target_survive_context_reduction(
    collective: Collective,
) -> None:
    from app.usecases.collective.context import reduce_context

    activity_id = await start_activity(collective)
    conversation = cast(ConversationDouble, collective.conversation)
    conversation.decisions.append(
        Decision(
            change=ActivityChange(
                action="update",
                activity_id=activity_id,
                expected_version=1,
                reason="Include support",
                next_step="Check support",
            )
        )
    )
    collective.receive("2", "保守費用も含めて", "master", 2, "alice")
    await collective.conversation_step(2)
    collective.schedule(3)
    turn = collective._claim("work", 3)
    assert turn is not None and turn.context is not None
    context = turn.context
    while (reduced := reduce_context(context)) is not None:
        context = reduced
    sources = {source for item in context.items for source in item.sources}
    assert {"discord:1", "discord:2"} <= sources


@pytest.mark.anyio
async def test_database_failure_after_work_recovers_file_without_reexecution(
    collective: Collective, monkeypatch: pytest.MonkeyPatch
) -> None:
    activity_id = await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    result = finished()
    codex.results.append(result)
    original = collective._save_output
    failed = False

    def fail_once(turn: Turn, output: str, now: float) -> None:
        nonlocal failed
        if not failed:
            failed = True
            codex.saved_output = output
            raise RuntimeError("Database temporarily unavailable")
        original(turn, output, now)

    monkeypatch.setattr(collective, "_save_output", fail_once)
    await collective.work_step(2)
    assert collective.store.read().activities[activity_id].status == "ready"
    await collective.work_step(10)
    assert collective.store.read().activities[activity_id].status == "done"
    assert len(codex.contexts) == 1


def test_related_high_priority_source_group_outlives_unrelated_history(
    collective: Collective,
) -> None:
    from app.usecases.collective.context import reduce_context

    collective.receive("1", "Now", "master", 1, "alice")
    turn = collective._claim("conversation", 1)
    assert turn is not None and turn.context is not None
    context = turn.context.model_copy(
        update={
            "items": [
                ContextItem(
                    id="old-related", priority="low", sources=["a"], content="history"
                ),
                ContextItem(
                    id="note", priority="high", sources=["a"], content="related note"
                ),
                ContextItem(
                    id="unrelated", priority="low", sources=["b"], content="old chat"
                ),
            ]
        }
    )
    reduced = reduce_context(context)
    assert reduced is not None
    assert [item.id for item in reduced.items] == ["old-related", "note"]
