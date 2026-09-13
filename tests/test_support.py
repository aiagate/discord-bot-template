"""Acceptance scenarios for autonomous continuity, cooperation, and interruption."""

from pathlib import Path

import anyio
import pytest

from app.contracts.messages.support import Communication, Context, Memory, Outcome
from app.contracts.ports.support import EvidenceWriter
from app.infrastructure.store import LocalStore, runner_lock
from app.usecases.support import SupportRunner


def decision(action: object = "continue", **changes: object) -> Outcome:
    """Build an explicit model decision for lifecycle scenarios."""
    return Outcome.model_validate(
        {
            "action": action,
            "summary": "確認した結果です。",
            "rationale": "目的に必要な確認が残っています。",
            "next_step": "資料を確認する",
            "communication": Communication(
                content="確認した結果です。",
                question=str(changes.get("next_step", "資料を確認する"))
                if action == "ask"
                else "",
            ),
            **changes,
        }
    )


class ScriptedThinker:
    """Expose context received by independent character turns."""

    def __init__(self, *outcomes: Outcome) -> None:
        self.outcomes = list(outcomes)
        self.contexts: list[Context] = []

    async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
        """Record an observable action separately from the claimed result."""
        self.contexts.append(context)
        await record("commandExecution", '{"command":"check","exit_code":0}')
        return self.outcomes.pop(0)


@pytest.mark.anyio
async def test_autonomous_continuity_handoff_question_and_memory(
    store: LocalStore,
) -> None:
    """U1–U7: no new input is needed until a real question is reached."""
    activity = store.create(
        "プロジェクトの未解決事項を進める",
        ("根拠を示す",),
        "資料を調査する",
        "dorothy",
        now=100,
    )
    thinker = ScriptedThinker(
        decision(memories=(Memory(key="project", content="確認できた設計上の前提。"),)),
        decision("sleep", delay_seconds=60),
        decision("handoff", recipient="astra", next_step="境界を別の観点で検証する"),
        decision("ask", next_step="対象はAですか。"),
        decision(
            "complete",
            next_step="",
            evidence=("原文と検証記録を確認した",),
            achieved=(0,),
        ),
    )
    now = 100.0
    runner = SupportRunner(store, thinker, clock=lambda: now)
    assert await runner.tick()
    assert await runner.tick()
    assert store.current(activity.id).status == "sleeping"
    assert not await runner.tick()
    now = 160
    assert await runner.tick()
    assert await runner.tick()
    assert thinker.contexts[-1].character.id == "astra"
    assert thinker.contexts[-1].activity.next_step == "境界を別の観点で検証する"
    assert store.current(activity.id).status == "waiting"
    assert not await runner.tick()
    original = "  対象はAです。\n以前の推測を訂正します。\n"
    store.inform(activity.id, original, now=now)
    assert await runner.tick()
    assert store.current(activity.id).status == "done"
    assert not await runner.tick()
    final_context = thinker.contexts[-1]
    assert final_context.master == "選び直せる形で、自分で必要な一手を判断する。"
    assert any(event.content == original for event in final_context.events)
    assert not (final_context.memory_root / "project.md").exists()
    note = (store.workspace("dorothy") / "memory" / "project.md").read_text()
    assert "確認できた設計上の前提" in note
    assert "../evidence/" in note
    assert (
        len(
            [
                event
                for event in store.events(activity.id)
                if event.kind == "commandExecution"
            ]
        )
        == 5
    )


@pytest.mark.anyio
async def test_scheduled_observation_reads_changed_subject_without_human_input(
    store: LocalStore,
) -> None:
    """U2: a later wake can observe actual changes instead of replaying old input."""
    activity = store.create(
        "資料の状態を確認し続ける", ("更新を見つける",), "資料を読む", "noa", now=100
    )
    subject = store.root / "subject.txt"
    subject.write_text("before")
    observed: list[str] = []

    class Observer:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            content = subject.read_text()
            observed.append(content)
            await record("observation", content)
            return decision(
                "sleep", delay_seconds=60, summary=content, communication=None
            )

    now = 100.0
    runner = SupportRunner(store, Observer(), clock=lambda: now)
    await runner.tick()
    subject.write_text("after")
    now = 160
    await runner.tick()
    assert observed == ["before", "after"]
    assert store.current(activity.id).runs == 2
    assert not store.pending_notices()


@pytest.mark.anyio
async def test_budget_stops_autonomous_loop_until_explicit_extension(
    store: LocalStore,
) -> None:
    """U4: continuing forever cannot create an unbounded execution budget."""
    activity = store.create(
        "継続支援", ("継続する",), "資料を確認する", "noa", now=100, max_runs=1
    )
    thinker = ScriptedThinker(decision(), decision())
    runner = SupportRunner(store, thinker, clock=lambda: 100)
    await runner.tick()
    assert not await runner.tick()
    assert store.current(activity.id).status == "exhausted"
    store.inform(activity.id, "追加情報", now=100)
    assert not await runner.tick()
    store.control(activity.id, resume=True, budget=1, now=100)
    assert await runner.tick()
    assert len(thinker.contexts) == 2


@pytest.mark.anyio
@pytest.mark.parametrize("control", ["stop", "input"])
async def test_new_user_action_cancels_old_decision(
    store: LocalStore, control: str
) -> None:
    """U7: a running agent cannot overwrite a newer stop or correction."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    started = anyio.Event()
    cancelled = anyio.Event()

    class WaitingThinker:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            started.set()
            try:
                await anyio.sleep_forever()
            finally:
                cancelled.set()
            raise AssertionError("unreachable")

    runner = SupportRunner(
        store, WaitingThinker(), clock=lambda: 100, check_interval=0.01
    )
    async with anyio.create_task_group() as group:
        group.start_soon(runner.tick)
        await started.wait()
        if control == "stop":
            store.control(activity.id, now=100)
        else:
            store.inform(activity.id, "方針を訂正します", now=100)
    assert cancelled.is_set()
    assert store.current(activity.id).status == (
        "stopped" if control == "stop" else "ready"
    )
    assert not store.pending_notices()


@pytest.mark.anyio
async def test_timeout_and_failure_leave_retryable_evidence(store: LocalStore) -> None:
    """U3/U4: failed attempts remain unfinished and recover with backoff."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)

    class HangingThinker:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            await record("commandExecution", '{"exit_code":1}')
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

    runner = SupportRunner(
        store, HangingThinker(), timeout=0.02, clock=lambda: 100, check_interval=0.01
    )
    assert await runner.tick()
    current = store.current(activity.id)
    assert current.status == "sleeping"
    assert current.wake_at == 160
    assert "TimeoutError" in store.pending_notices()[0].content
    assert not await runner.tick()


@pytest.mark.anyio
async def test_runtime_shutdown_preserves_unfinished_state(store: LocalStore) -> None:
    """U4: shutting down never marks an interrupted activity done."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    started = anyio.Event()

    class HangingThinker:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            started.set()
            await anyio.sleep_forever()
            raise AssertionError("unreachable")

    async with anyio.create_task_group() as group:
        group.start_soon(SupportRunner(store, HangingThinker(), clock=lambda: 100).tick)
        await started.wait()
        group.cancel_scope.cancel()
    assert store.current(activity.id).status == "sleeping"


def test_recover_after_crash_preserves_purpose_and_marks_unknown_result(
    store: LocalStore,
) -> None:
    """U4: a new process recovers durable work without inventing a result."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    assert store.claim(100) is not None
    reopened = LocalStore(store.root)
    with runner_lock(store.root):
        reopened.recover(200)
        current = reopened.current(activity.id)
        assert current.status == "ready"
        assert current.runs == 1
        assert "外部操作" in current.next_step
        assert reopened.claim(200) is not None


def test_single_executor_lock_does_not_block_control(store: LocalStore) -> None:
    """U4/U7: concurrent runners are rejected while user controls still work."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    with runner_lock(store.root):
        with pytest.raises(RuntimeError, match="既に実行中"):
            with runner_lock(store.root):
                pass
        store.control(activity.id, now=100)
    with runner_lock(store.root):
        assert store.current(activity.id).status == "stopped"


def test_stale_result_cannot_write_memory_notice_or_new_owner(
    store: LocalStore,
) -> None:
    """U5/U7: late results are evidence only, never current decisions."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    claimed = store.claim(100)
    assert claimed is not None
    store.inform(activity.id, "古い前提は誤り", now=101)
    assert not store.finish(
        claimed,
        decision(
            "handoff",
            recipient="astra",
            memories=(Memory(key="old", content="古い前提"),),
        ),
        102,
    )
    store.project()
    assert not (store.workspace("noa") / "memory" / "old.md").exists()
    assert not store.pending_notices()
    assert store.current(activity.id).character_id == "noa"


@pytest.mark.parametrize(
    "outcome",
    [
        decision("complete", next_step="", achieved=(0,), evidence=("一つ目だけ",)),
        decision("handoff", recipient="noa"),
        decision("handoff", recipient="missing"),
    ],
)
def test_decision_must_match_activity_and_available_colleagues(
    store: LocalStore,
    outcome: Outcome,
) -> None:
    """U3/U5: incomplete criteria or invalid recipients cannot commit a result."""
    activity = store.create("確認", ("一つ目", "二つ目"), "資料のみ", "noa", now=100)
    claimed = store.claim(100)
    assert claimed is not None
    with pytest.raises(ValueError):
        store.finish(claimed, outcome, 101)
    assert store.current(activity.id) == claimed
    assert not store.pending_notices()
    assert all(event.kind != "decision" for event in store.events(activity.id))


def test_projection_failure_can_retry_without_repeating_activity(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """U6: filesystem failure does not lose an already committed decision."""
    from app.infrastructure import store as module

    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    claimed = store.claim(100)
    assert claimed is not None
    store.finish(
        claimed, decision(memories=(Memory(key="learned", content="学んだこと"),)), 100
    )
    write = module.atomic_write

    def fail(path: Path, content: str) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(module, "atomic_write", fail)
    with pytest.raises(OSError):
        store.project()
    monkeypatch.setattr(module, "atomic_write", write)
    LocalStore(store.root).project()
    assert (
        "学んだこと" in (store.workspace("noa") / "memory" / "learned.md").read_text()
    )
    assert store.current(activity.id).runs == 1


def test_input_dedup_and_observation_do_not_revive_stopped_work(
    store: LocalStore,
) -> None:
    """U7: replayed input is stored once, and observation grants no resume authority."""
    activity = store.create("作業", ("確認",), "確認のみ", "noa", now=100)
    first = store.inform(activity.id, "原文", external_key="message:1", now=100)
    second = store.inform(activity.id, "原文", external_key="message:1", now=100)
    assert first.revision == second.revision
    store.control(activity.id, now=100)
    store.inform(activity.id, "変化を観測", observation=True, now=200)
    assert store.current(activity.id).status == "stopped"
    assert store.claim(300) is None


@pytest.mark.parametrize(
    "changes",
    [
        {"action": "complete", "next_step": ""},
        {
            "action": "complete",
            "next_step": "",
            "evidence": ["根拠"],
            "achieved": [0],
            "communication": None,
        },
        {"action": "sleep"},
        {"action": "handoff"},
        {"action": "ask", "next_step": ""},
        {"delay_seconds": 60},
        {"recipient": "../noa"},
        {"action": "ask", "communication": None},
        {"achieved": [0]},
        {
            "memories": [
                {"key": "same", "content": "A"},
                {"key": "same", "content": "B"},
            ]
        },
    ],
)
def test_invalid_decisions_are_rejected(changes: dict[str, object]) -> None:
    """U3: invalid output cannot become an actionable lifecycle transition."""
    with pytest.raises(ValueError):
        decision(**changes)
