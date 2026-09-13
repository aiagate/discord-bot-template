"""User-facing control works independently of model credentials."""

import argparse
import json
from pathlib import Path

import anyio
import pytest

from app import cli
from app.contracts.messages.conversation import (
    ConversationContext,
    ConversationDecision,
)
from app.contracts.messages.support import (
    Communication,
    Context,
    DeliveryAttempt,
    Outcome,
)
from app.contracts.ports.support import EvidenceWriter
from app.infrastructure.communication import FilePublisher
from app.infrastructure.store import LocalStore
from app.usecases.support import Communicator, SupportRunner


def test_cli_registers_original_input_controls_and_evidence(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """U1/U7: purpose and controls can be operated without a model or Discord."""
    root = tmp_path / "state"
    master = tmp_path / "master.md"
    master.write_text("マスターの思想")
    prefix = ["--root", str(root)]
    cli.main([*prefix, "init", "--master-file", str(master)])
    capsys.readouterr()
    cli.main(
        [
            *prefix,
            "add",
            "継続支援",
            "--criterion",
            "根拠を示す",
            "--scope",
            "資料を調べる",
            "--repo",
            "https://example.invalid/team/project.git",
        ]
    )
    activity_id = capsys.readouterr().out.strip()
    assert LocalStore(root).current(activity_id).repositories == (
        "https://example.invalid/team/project.git",
    )
    cli.main([*prefix, "note", activity_id, "原文", "--key", "note:1"])
    cli.main([*prefix, "observe", activity_id, "新しい観測"])
    cli.main([*prefix, "status", activity_id])
    assert "継続支援" in capsys.readouterr().out
    cli.main([*prefix, "stop", activity_id])
    cli.main([*prefix, "status"])
    assert "stopped" in capsys.readouterr().out
    cli.main([*prefix, "resume", activity_id, "--budget", "2"])
    cli.main([*prefix, "history", activity_id])
    assert "原文" in capsys.readouterr().out
    assert (root / "master.md").read_text() == "マスターの思想"
    with pytest.raises(SystemExit, match="見つかりません"):
        cli.main([*prefix, "status", "missing"])


def test_expression_config_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """An optional speaker does not silently guess a provider model."""
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("COLLECTIVE_GEMINI_MODEL", raising=False)
    assert cli.make_speaker() is None
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    assert cli.make_speaker() is None
    monkeypatch.delenv("GEMINI_API_KEY")
    monkeypatch.setenv("COLLECTIVE_GEMINI_MODEL", "expression-model")
    with pytest.raises(ValueError, match="COLLECTIVE_GEMINI_MODEL"):
        cli.make_speaker()


@pytest.mark.anyio
async def test_run_once_uses_same_runtime_and_publishes_result(
    store: LocalStore,
) -> None:
    """The one-shot command exercises real state and publication adapters."""
    activity = store.create("確認", ("資料を読む",), "資料のみ", "noa", now=1)

    class Thinker:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            (context.workspace / "report.md").write_text("確認結果")
            await record("fileChange", "report.md")
            return Outcome(
                action="complete",
                summary="確認しました。",
                communication=Communication(content="確認しました。"),
                rationale="資料を確認した",
                next_step="",
                evidence=("report.md",),
                achieved=(0,),
            )

    communicator = Communicator(store, FilePublisher(store.root / "messages"))
    await cli.serve(
        SupportRunner(store, Thinker()), communicator, store, interval=1, once=True
    )
    assert store.current(activity.id).status == "done"
    assert list((store.root / "messages").glob("*.md"))


@pytest.mark.anyio
async def test_say_and_run_wire_conversation_without_starting_stopped_work(
    store: LocalStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The CLI uses the selected thinker and keeps a stopped activity stopped."""
    activity = store.create("確認", ("資料を読む",), "資料のみ", "noa", now=1)
    stopped = store.control(activity.id)
    cli.main(["--root", str(store.root), "say", activity.id, "こんにちは"])

    class Thinker:
        closed = False

        async def think(self, context: ConversationContext) -> ConversationDecision:
            assert context.message.content == "こんにちは"
            return ConversationDecision(
                action="reply", content="こんにちは。", rationale="挨拶する"
            )

        async def close(self) -> None:
            self.closed = True

    thinker = Thinker()

    def make_thinker() -> Thinker:
        return thinker

    def no_speaker() -> None:
        return None

    monkeypatch.setattr(cli, "make_conversation_thinker", make_thinker)
    monkeypatch.setattr(cli, "make_speaker", no_speaker)
    await cli.run(store, cli.parser().parse_args(["run", "--once"]))
    assert thinker.closed
    assert store.current(activity.id) == stopped
    assert not store.pending_notices()
    assert "こんにちは" in next((store.root / "messages").glob("*.md")).read_text()


@pytest.mark.anyio
async def test_slow_delivery_does_not_hold_up_next_activity(store: LocalStore) -> None:
    """U3/U7: support continues while its communication loop is unavailable."""
    activity = store.create("継続確認", ("確認",), "資料のみ", "noa", now=1, max_runs=2)
    second_run = anyio.Event()

    class Thinker:
        async def run(self, context: Context, record: EvidenceWriter) -> Outcome:
            if context.activity.runs == 2:
                second_run.set()
            return Outcome(
                action="continue",
                summary="確認しました。",
                communication=Communication(content="確認しました。"),
                rationale="続きがある",
                next_step="次の確認",
            )

    class Publisher:
        async def send(self, notice: object, character: object) -> None:
            await anyio.sleep_forever()

    with anyio.fail_after(2):
        async with anyio.create_task_group() as group:

            async def serve() -> None:
                await cli.serve(
                    SupportRunner(store, Thinker()),
                    Communicator(store, Publisher()),
                    store,
                    interval=0.01,
                )

            group.start_soon(serve)
            await second_run.wait()
            group.cancel_scope.cancel()
    assert store.current(activity.id).runs == 2


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [0, -1, float("nan"), float("inf")])
async def test_run_rejects_invalid_timing_before_starting_models(
    store: LocalStore,
    invalid: float,
) -> None:
    """Reject a busy-poll runtime instead of starting it."""
    with pytest.raises(ValueError):
        await cli.run(store, argparse.Namespace(interval=invalid, timeout=1))
    with pytest.raises(ValueError):
        await cli.run(store, argparse.Namespace(interval=1, timeout=invalid))


def test_pending_exposes_unconfirmed_attempt_without_rerunning_work(
    store: LocalStore,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """An operator can distinguish unattempted notices from uncertain sends."""
    activity = store.create("確認", ("条件",), "範囲", "noa", now=1)
    store.command(activity.id, "!status", "discord:1")
    notice = store.pending_notices()[0]
    store.save_discord_attempt(notice.id, DeliveryAttempt(started_at=12))
    cli.main(["--root", str(store.root), "pending"])
    result = json.loads(capsys.readouterr().out)
    assert result["notice"]["id"] == notice.id
    assert result["attempt"] == {"started_at": 12, "receipt": None}
    assert store.current(activity.id).runs == 0
