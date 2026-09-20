"""Exercise the SDK boundary without network calls or paid model execution."""

import json
from collections.abc import AsyncIterator
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import anyio
import pytest
from openai_codex import Sandbox, SkillInput
from openai_codex.generated.v2_all import (
    ItemCompletedNotification,
    TurnCompletedNotification,
)

from app.contracts.ports.collective import HoldTurn
from app.infrastructure.collective.codex import CodexWorker
from app.infrastructure.collective.workspace import CharacterWorkspaces
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import CodexDouble
from tests.collective.test_runtime import finished, start_activity


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [False, True])
async def test_sdk_schema_skill_result_checkpoint_and_cleanup(
    collective: Collective, monkeypatch: pytest.MonkeyPatch, invalid: bool
) -> None:
    await start_activity(collective)
    collective.schedule(2)
    double = cast(CodexDouble, collective.codex)
    double.results.append(finished())
    await collective.work_step(2)
    context = double.contexts[0].model_copy(update={"attempt": 2})
    cast(CharacterWorkspaces, collective.workspaces).prepare(
        context, collective.store.read()
    )
    result = finished().model_dump(mode="json")
    result["evidence"] = [
        {"criterion": key, "observation": value}
        for key, value in finished().evidence.items()
    ]
    if invalid:
        result["evidence"].append(result["evidence"][0])
    final = ItemCompletedNotification.model_validate(
        {
            "completedAtMs": 1,
            "threadId": "thread",
            "turnId": "turn",
            "item": {
                "type": "agentMessage",
                "id": "reply",
                "phase": "final_answer",
                "text": json.dumps(result),
            },
        }
    )
    done = TurnCompletedNotification.model_validate(
        {
            "threadId": "thread",
            "turn": {"id": "turn", "status": "completed", "items": []},
        }
    )

    async def stream() -> AsyncIterator[SimpleNamespace]:
        for event in (final, done):
            yield SimpleNamespace(payload=event)

    turn = MagicMock()
    turn.id = "turn"
    turn.stream = stream
    turn.interrupt = AsyncMock()
    thread = MagicMock()
    thread.id = "thread"
    thread.turn = AsyncMock(return_value=turn)
    client = MagicMock()
    client.thread_start = AsyncMock(return_value=thread)
    client.close = AsyncMock()
    factory = MagicMock(return_value=client)
    monkeypatch.setattr("app.infrastructure.collective.codex.AsyncCodex", factory)
    monkeypatch.setattr(
        "app.infrastructure.collective.codex.shutil.which",
        MagicMock(return_value="/bin/tool"),
    )
    monkeypatch.setenv("GEMINI_API_KEY", "must-not-appear-in-command")
    worker = CodexWorker(Path(context.references["agy_skill"]))
    monkeypatch.setattr(worker, "recover", AsyncMock(return_value=True))
    execution: dict[str, str] = {}

    async def record(kind: str, value: str) -> None:
        execution[kind] = value

    if invalid:
        with pytest.raises(HoldTurn):
            await worker.run_codex(context, record)
    else:
        returned = await worker.run_codex(context, record)
        assert returned.evidence == finished().evidence
        assert worker.saved_result(execution) == returned.model_dump_json()
    assert any(isinstance(item, SkillInput) for item in thread.turn.call_args.args[0])
    schema = thread.turn.call_args.kwargs["output_schema"]
    assert schema["properties"]["evidence"]["type"] == "array"
    assert schema["properties"]["evidence"]["items"]["additionalProperties"] is False
    assert context.activity is not None
    assert (
        schema["properties"]["evidence"]["items"]["properties"]["criterion"]["enum"]
        == context.activity.criteria
    )
    assert set(schema["required"]) == set(schema["properties"])
    config = factory.call_args.args[0]
    assert "must-not-appear-in-command" not in " ".join(config.launch_args_override)
    assert client.thread_start.call_args.kwargs["sandbox"] == Sandbox.workspace_write
    assert execution["thread_id"] == "thread" and execution["turn_id"] == "turn"
    client.close.assert_awaited_once()
    assert not worker.running


@pytest.mark.anyio
async def test_saved_result_and_missing_tools_fail_before_execution(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    worker = CodexWorker(tmp_path / "SKILL.md")
    assert worker.saved_result({}) is None
    assert worker.saved_result({"result_file": str(tmp_path / "missing")}) is None
    assert await worker.interrupt("not-running")


@pytest.mark.anyio
async def test_stop_during_thread_start_prevents_a_work_turn(
    collective: Collective, monkeypatch: pytest.MonkeyPatch
) -> None:
    await start_activity(collective)
    collective.schedule(2)
    double = cast(CodexDouble, collective.codex)
    double.results.append(finished())
    await collective.work_step(2)
    context = double.contexts[0].model_copy(update={"attempt": 2})
    cast(CharacterWorkspaces, collective.workspaces).prepare(
        context, collective.store.read()
    )
    entered = anyio.Event()
    release = anyio.Event()
    thread = MagicMock()
    thread.id = "thread"
    thread.turn = AsyncMock()

    async def start_thread(**kwargs: object) -> MagicMock:
        entered.set()
        await release.wait()
        return thread

    client = MagicMock()
    client.thread_start = start_thread
    client.close = AsyncMock()
    monkeypatch.setattr(
        "app.infrastructure.collective.codex.AsyncCodex", MagicMock(return_value=client)
    )
    monkeypatch.setattr(
        "app.infrastructure.collective.codex.shutil.which",
        MagicMock(return_value="/bin/tool"),
    )
    worker = CodexWorker(Path(context.references["agy_skill"]))
    monkeypatch.setattr(worker, "recover", AsyncMock(side_effect=[False, True]))

    async def record(kind: str, value: str) -> None:
        pass

    async def run() -> None:
        with pytest.raises(HoldTurn, match="Stopped before"):
            await worker.run_codex(context, record)

    async with anyio.create_task_group() as group:
        group.start_soon(run)
        await entered.wait()
        assert not await worker.interrupt(context.run_id)
        release.set()
    thread.turn.assert_not_awaited()
    client.close.assert_awaited_once()
