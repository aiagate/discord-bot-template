"""Conversation progresses independently while explicit intent can affect work."""

import anyio
import pytest

from app import cli
from app.contracts.messages.conversation import (
    ConversationContext,
    ConversationDecision,
)
from app.contracts.messages.support import Context, Notice, Outcome
from app.contracts.ports.support import EvidenceWriter
from app.infrastructure.communication import FilePublisher
from app.infrastructure.store import LocalStore
from app.usecases.conversation import ConversationRunner
from app.usecases.support import Communicator, SupportRunner


class Thinker:
    """Record the shared context and return one explicit conversation decision."""

    def __init__(self, action: str = "reply") -> None:
        self.contexts: list[ConversationContext] = []
        self.decision = ConversationDecision.model_validate(
            {"action": action, "content": "こんにちは。", "rationale": "発言に答える"}
        )

    async def think(self, context: ConversationContext) -> ConversationDecision:
        self.contexts.append(context)
        return self.decision

    async def close(self) -> None:
        pass


@pytest.mark.anyio
async def test_greeting_is_durable_and_never_restarts_work(store: LocalStore) -> None:
    """U8: greeting, expression, and delivery leave a running activity intact."""
    activity = store.create("継続支援", ("確認",), "資料を調べる", "dorothy", now=1)
    claimed = store.claim(1)
    assert claimed is not None
    raw = " こんにちは\n"
    store.receive(activity.id, raw, external_key="discord:1")
    store.receive(activity.id, raw, external_key="discord:1")
    store = LocalStore(store.root)
    thinker = Thinker()
    runner = ConversationRunner(store, thinker)
    assert await runner.tick()
    assert not await runner.tick()
    assert thinker.contexts[0].message.content == raw
    assert store.current(activity.id) == claimed
    assert len(store.pending_notices()) == 1

    class Speaker:
        async def render(self, notice: object, character: object) -> str:
            return "こんにちは、マスター。"

    assert (
        await Communicator(
            store, FilePublisher(store.root / "messages"), Speaker()
        ).flush()
        == 1
    )
    assert store.current(activity.id) == claimed
    assert store.events(activity.id)[-1].content == "こんにちは、マスター。"


@pytest.mark.anyio
async def test_dialogue_and_delivery_finish_during_ongoing_work(
    store: LocalStore,
) -> None:
    """U8: the production loops do not wait for the action thinker's completion."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    started = anyio.Event()
    delivered = anyio.Event()

    class Worker:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            started.set()
            await anyio.sleep_forever()
            raise AssertionError("Work must still be running at delivery")

    class Publisher:
        async def send(self, notice: Notice, character: object) -> None:
            assert "こんにちは" in notice.content
            assert store.current(activity.id).status == "running"
            delivered.set()

    with anyio.fail_after(5):
        async with anyio.create_task_group() as group:

            async def serve() -> None:
                await cli.serve(
                    SupportRunner(store, Worker()),
                    Communicator(store, Publisher()),
                    store,
                    interval=0.01,
                    conversation=ConversationRunner(store, Thinker()),
                )

            group.start_soon(serve)
            await started.wait()
            revision = store.current(activity.id).revision
            store.receive(activity.id, "こんにちは")
            await delivered.wait()
            assert store.current(activity.id).revision == revision
            assert store.current(activity.id).runs == 1
            group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_model_failure_preserves_input_for_another_thinker(
    store: LocalStore,
) -> None:
    """Provider replacement can resume the same saved conversation."""
    activity = store.create("支援", ("確認",), "資料", "astra", now=1)
    store.receive(activity.id, "どう思う？")

    class Unavailable(Thinker):
        async def think(self, context: ConversationContext) -> ConversationDecision:
            raise RuntimeError("provider unavailable")

    with pytest.raises(RuntimeError):
        await ConversationRunner(store, Unavailable()).tick()
    assert store.pending_conversation() is not None
    assert store.current(activity.id) == activity
    assert not store.pending_notices()
    assert await ConversationRunner(LocalStore(store.root), Thinker()).tick()
    assert len(store.pending_notices()) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["work", "stop", "resume"])
async def test_only_explicit_intent_changes_work(
    store: LocalStore, action: str
) -> None:
    """U7/U8: persist the original request and report the actual applied state."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    if action == "resume":
        store.control(activity.id)
    else:
        store.claim(1)
    before = store.current(activity.id)
    store.receive(activity.id, "対象はBです。" if action == "work" else action)
    assert store.current(activity.id) == before
    assert await ConversationRunner(store, Thinker(action)).tick()
    after = store.current(activity.id)
    assert after.revision == before.revision + 1
    assert after.runs == before.runs
    assert after.status == ("stopped" if action == "stop" else "ready")
    if action == "work":
        assert any(
            event.kind == "input" and event.content == "対象はBです。"
            for event in store.events(activity.id)
        )
    assert len(store.pending_notices()) == 1


@pytest.mark.anyio
@pytest.mark.parametrize("action", ["work", "resume"])
@pytest.mark.parametrize("control_before_thinking", [True, False])
async def test_newer_stop_always_wins_over_pending_conversation(
    store: LocalStore,
    action: str,
    control_before_thinking: bool,
) -> None:
    """A queued or in-flight old request cannot undo a later master's stop."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    store.receive(activity.id, "再開して")
    message = store.pending_conversation()
    assert message is not None
    if control_before_thinking:
        store.control(activity.id)
    context = store.conversation_context(message)
    if not control_before_thinking:
        store.control(activity.id)
    stopped = store.current(activity.id)
    decision = Thinker(action).decision
    assert store.finish_conversation(context, decision)
    assert store.current(activity.id) == stopped
    assert "その後に届いた指示" in store.pending_notices()[0].content
    assert not store.finish_conversation(context, decision)
    assert len(store.pending_notices()) == 1


@pytest.mark.anyio
async def test_reply_rechecks_changed_work_snapshot(store: LocalStore) -> None:
    """A progress answer is regenerated when its work snapshot became stale."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    store.receive(activity.id, "今の状況は？")
    message = store.pending_conversation()
    assert message is not None
    context = store.conversation_context(message)
    store.control(activity.id)
    assert not store.finish_conversation(context, Thinker().decision)
    thinker = Thinker()
    await ConversationRunner(store, thinker).tick()
    assert thinker.contexts[0].activity.status == "stopped"


@pytest.mark.anyio
async def test_work_information_does_not_implicitly_resume_stopped_activity(
    store: LocalStore,
) -> None:
    """A correction is saved while stopping remains an explicit master choice."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    store.control(activity.id)
    store.receive(activity.id, "対象を訂正します")
    await ConversationRunner(store, Thinker("work")).tick()
    assert store.current(activity.id).status == "stopped"
    assert "再開の指示が必要" in store.pending_notices()[0].content


def test_context_uses_shared_identity_memory_and_delivered_words(
    store: LocalStore,
) -> None:
    """Model choice does not fork memory, identity, or what the master heard."""
    activity = store.create("支援", ("確認",), "資料", "astra", now=1)
    store.record(activity, "commandExecution", "private tool output", 1)
    store.receive(activity.id, "こんにちは")
    first = store.pending_conversation()
    assert first is not None
    store.finish_conversation(store.conversation_context(first), Thinker().decision)
    notice = store.pending_notices()[0]
    store.save_rendered(notice.id, "マスター、こんにちは。")
    store.delivered(notice.id)
    store.delivered(notice.id)
    (store.workspace("astra") / "memory" / "learned.md").write_text(
        "確認済みの理解。出典: evidence/X"
    )
    store.receive(activity.id, "さっき何て言った？")
    second = store.pending_conversation()
    assert second is not None
    context = store.conversation_context(second)
    assert context.character == store.character("astra")
    assert context.master == (store.root / "master.md").read_text()
    assert "出典:" in context.memories["learned"]
    assert sum(event.kind == "delivered" for event in context.history) == 1
    assert "マスター、こんにちは。" in context.model_dump_json()
    assert "private tool output" not in context.model_dump_json()


def test_reply_and_work_update_rollback_together(
    store: LocalStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A persistence failure cannot acknowledge work it has failed to save."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    store.receive(activity.id, "対象を訂正します")
    message = store.pending_conversation()
    assert message is not None
    context = store.conversation_context(message)

    def unavailable(*args: object) -> None:
        raise OSError("storage unavailable")

    monkeypatch.setattr(store, "_notice", unavailable)
    with pytest.raises(OSError):
        store.finish_conversation(context, Thinker("work").decision)
    assert store.current(activity.id) == activity
    assert store.pending_conversation() == message
    assert not store.pending_notices()
    assert all(event.kind != "input" for event in store.events(activity.id))
