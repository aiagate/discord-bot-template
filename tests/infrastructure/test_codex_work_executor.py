"""Exercise the SDK adapter and real local sandbox without model calls."""

import asyncio
import io
import json
import sys
import zipfile
from collections.abc import AsyncIterator
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from openai_codex import ApprovalMode, AsyncCodex, AsyncThread, AsyncTurnHandle
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    CommandExecutionThreadItem,
    ItemCompletedNotification,
    ItemStartedNotification,
    MessagePhase,
    ReasoningEffort,
    ThreadItem,
    Turn,
    TurnCompletedNotification,
    TurnStatus,
    WebSearchThreadItem,
)
from openai_codex.models import Notification

from app.contracts.messages.character_work import CharacterWork, CharacterWorkError
from app.infrastructure.codex import work_executor
from app.infrastructure.codex.work_executor import CodexCharacterWorkExecutor


def _task() -> CharacterWork:
    return CharacterWork("100", "456", "123", "2", "lilia", "調べて", "100")


def _message(text: str, phase: MessagePhase) -> Notification:
    return Notification(
        method="item/completed",
        payload=ItemCompletedNotification(
            thread_id="thread-1",
            turn_id="turn-1",
            completed_at_ms=1,
            item=ThreadItem(
                root=AgentMessageThreadItem(
                    id="message-1",
                    type="agentMessage",
                    text=text,
                    phase=phase,
                )
            ),
        ),
    )


def _completed(status: TurnStatus = TurnStatus.completed) -> Notification:
    return Notification(
        method="turn/completed",
        payload=TurnCompletedNotification(
            thread_id="thread-1",
            turn=Turn(id="turn-1", items=[], status=status),
        ),
    )


def _client(
    monkeypatch: pytest.MonkeyPatch, events: list[Notification]
) -> tuple[MagicMock, MagicMock, MagicMock]:
    async def stream() -> AsyncIterator[Notification]:
        for event in events:
            yield event

    turn = MagicMock(spec=AsyncTurnHandle)
    turn.stream.side_effect = stream
    turn.steer = AsyncMock()
    turn.interrupt = AsyncMock()
    thread = MagicMock(spec=AsyncThread)
    thread.id = "thread-1"
    thread.turn = AsyncMock(return_value=turn)
    client = MagicMock(spec=AsyncCodex)
    client.thread_start = AsyncMock(return_value=thread)
    client.thread_resume = AsyncMock(return_value=thread)
    client.close = AsyncMock()
    monkeypatch.setattr(work_executor, "AsyncCodex", MagicMock(return_value=client))
    return client, thread, turn


@pytest.mark.anyio
@pytest.mark.parametrize("resume", [False, True])
async def test_session_precedes_execution_and_only_final_answer_is_result(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool
) -> None:
    client, thread, turn = _client(
        monkeypatch,
        [
            _message("途中経過", MessagePhase.commentary),
            _message("最終結果", MessagePhase.final_answer),
            _completed(),
        ],
    )
    executor = CodexCharacterWorkExecutor(tmp_path, None)
    task = _task()
    if resume:
        directory = await executor.prepare_workspace(task)
        task = replace(task, thread_id="thread-1", cwd=str(directory))
    events = executor.run(task, "Liliaとして調査")
    session = await anext(events)
    assert session.kind == "session" and session.thread_id == "thread-1"
    thread.turn.assert_not_awaited()
    progress = await anext(events)
    assert progress.text == "途中経過"
    assert await executor.steer("100", "補足")
    turn.steer.assert_awaited_once_with("補足")
    remaining = [event async for event in events]
    assert [(item.kind, item.text) for item in remaining] == [("completed", "最終結果")]
    start = client.thread_resume if resume else client.thread_start
    assert start.await_args is not None
    assert start.await_args.kwargs["approval_mode"] == ApprovalMode.deny_all
    assert "sandbox" not in start.await_args.kwargs
    thread.turn.assert_awaited_once_with(task.prompt)
    turn.interrupt.assert_not_awaited()
    client.close.assert_awaited_once()
    assert not await executor.steer("100", "終了後")


@pytest.mark.anyio
@pytest.mark.parametrize("resume", [False, True])
async def test_turn_receives_configured_reasoning_effort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, resume: bool
) -> None:
    client, thread, _ = _client(
        monkeypatch,
        [_message("最終結果", MessagePhase.final_answer), _completed()],
    )
    executor = CodexCharacterWorkExecutor(
        tmp_path,
        None,
        model="gpt-5.6-luna",
        reasoning_effort="max",
    )
    task = _task()
    if resume:
        directory = await executor.prepare_workspace(task)
        task = replace(task, thread_id="thread-1", cwd=str(directory))

    _ = [event async for event in executor.run(task, "調査")]

    start = client.thread_resume if resume else client.thread_start
    assert start.await_args is not None
    assert start.await_args.kwargs["model"] == "gpt-5.6-luna"
    thread.turn.assert_awaited_once_with(
        task.prompt,
        effort=ReasoningEffort.max,
    )


@pytest.mark.anyio
@pytest.mark.parametrize("terminal", [None, TurnStatus.completed, TurnStatus.failed])
async def test_disconnect_or_missing_result_is_failure_and_always_closes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, terminal: TurnStatus | None
) -> None:
    events = [_completed(terminal)] if terminal is not None else []
    client, _, turn = _client(monkeypatch, events)
    executor = CodexCharacterWorkExecutor(tmp_path, None)
    with pytest.raises(CharacterWorkError):
        _ = [event async for event in executor.run(_task(), "調査")]
    client.close.assert_awaited_once()
    assert turn.interrupt.await_count == (1 if terminal is None else 0)


@pytest.mark.anyio
async def test_cancellation_interrupts_only_own_turn(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _, turn = _client(
        monkeypatch, [_message("作業中", MessagePhase.commentary)]
    )
    executor = CodexCharacterWorkExecutor(tmp_path, None)
    events = executor.run(_task(), "調査")
    await anext(events)
    await anext(events)
    await events.aclose()
    turn.interrupt.assert_awaited_once()
    client.close.assert_awaited_once()


@pytest.mark.anyio
async def test_tool_limit_interrupts_instead_of_reporting_success(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = Notification(
        method="item/started",
        payload=ItemStartedNotification(
            thread_id="thread-1",
            turn_id="turn-1",
            started_at_ms=1,
            item=ThreadItem(
                root=WebSearchThreadItem(id="search", type="webSearch", query="SDK")
            ),
        ),
    )
    client, _, turn = _client(monkeypatch, [event] * 101)
    executor = CodexCharacterWorkExecutor(tmp_path, None)
    with pytest.raises(CharacterWorkError, match="操作回数"):
        _ = [item async for item in executor.run(_task(), "調査")]
    turn.interrupt.assert_awaited_once()
    client.close.assert_awaited_once()


@pytest.mark.anyio
@pytest.mark.parametrize("character_id", ["lilia", "noa", "mira", "helper_2"])
async def test_characters_get_separate_worktrees_at_head(
    tmp_path: Path,
    character_id: str,
) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    await work_executor._git(repository, "init", "-b", "main")
    (repository / "source.py").write_text("before\n")
    await work_executor._git(repository, "add", "source.py")
    await work_executor._git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    (repository / "source.py").write_text("uncommitted\n")
    executor = CodexCharacterWorkExecutor(tmp_path / "work", repository)
    task = replace(_task(), character_id=character_id)
    directory = await executor.prepare_workspace(task)
    assert (directory / "source.py").read_text() == "before\n"
    assert (repository / "source.py").read_text() == "uncommitted\n"
    assert (
        await work_executor._git(directory, "branch", "--show-current")
        == f"codex/{character_id}-100"
    )
    assert await executor.prepare_workspace(task) == directory
    with pytest.raises(CharacterWorkError, match="一致"):
        await executor.prepare_workspace(replace(task, cwd=str(repository)))
    with pytest.raises(CharacterWorkError, match="担当"):
        await executor.prepare_workspace(replace(task, id="../source"))
    plain_executor = CodexCharacterWorkExecutor(tmp_path / "work", None)
    with pytest.raises(CharacterWorkError, match="リポジトリ"):
        await plain_executor.prepare_workspace(task)
    folder_task = replace(task, id="101", last_message_id="101")
    folder = await plain_executor.prepare_workspace(folder_task)
    (folder / "memo.md").write_text("existing result")
    resumed = replace(folder_task, cwd=str(folder), thread_id="saved-session")
    assert await executor.prepare_workspace(resumed) == folder
    assert not (folder / ".git").exists()
    assert (folder / "memo.md").read_text() == "existing result"


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform != "linux", reason="Linux sandbox integration")
@pytest.mark.parametrize("character_id", ["lilia", "noa", "mira"])
async def test_git_workspaces_snapshot_changes_and_command_evidence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    character_id: str,
) -> None:
    repository = tmp_path / "source"
    repository.mkdir()
    await work_executor._git(repository, "init", "-b", "main")
    for path in ["changed.py", "deleted.py", "renamed.py", "unchanged.py"]:
        (repository / path).write_text("before = 1\n")
    (repository / ".gitignore").write_text("ignored/\n")
    await work_executor._git(repository, "add", ".")
    await work_executor._git(
        repository,
        "-c",
        "user.name=Test",
        "-c",
        "user.email=test@example.invalid",
        "commit",
        "-m",
        "initial",
    )
    command = Notification(
        method="item/completed",
        payload=ItemCompletedNotification(
            thread_id="thread-1",
            turn_id="turn-1",
            completed_at_ms=1,
            item=ThreadItem.model_validate(
                {
                    "id": "command-1",
                    "type": "commandExecution",
                    "command": "python -m pytest",
                    "commandActions": [],
                    "cwd": str(repository),
                    "status": "completed",
                    "exitCode": 1,
                    "aggregatedOutput": "1 failed",
                }
            ),
        ),
    )
    assert isinstance(command.payload, ItemCompletedNotification)
    assert isinstance(command.payload.item.root, CommandExecutionThreadItem)
    client, _, _ = _client(
        monkeypatch,
        [command, _message("修正完了", MessagePhase.final_answer), _completed()],
    )
    executor = CodexCharacterWorkExecutor(tmp_path / "work", repository)
    task = replace(_task(), character_id=character_id)
    events = executor.run(task, "実装して検証")
    session = await anext(events)
    assert session.cwd is not None
    directory = Path(session.cwd)
    (directory / "changed.py").write_text("after = 42\n")
    (directory / "deleted.py").unlink()
    (directory / "renamed.py").rename(directory / "名前変更.py")
    (directory / "調査メモ.md").write_text("調査結果")
    (directory / "ignored").mkdir()
    (directory / "ignored" / "cache.txt").write_text("cache")
    (directory / ".env").write_text("test-only-canary")
    (directory / "linked.txt").symlink_to(repository / "unchanged.py")
    remaining = [event async for event in events]
    client.close.assert_awaited_once()
    completed = remaining[-1]
    assert completed.kind == "completed" and completed.artifacts is not None
    (attachment,) = await executor.attachments(
        replace(task, artifacts=completed.artifacts)
    )
    with zipfile.ZipFile(io.BytesIO(attachment.data)) as archive:
        manifest = json.loads(archive.read("manifest.json"))
        assert archive.read("files/changed.py") == b"after = 42\n"
        assert archive.read("files/調査メモ.md").decode() == "調査結果"
        assert "files/unchanged.py" not in archive.namelist()
        assert "files/ignored/cache.txt" not in archive.namelist()
        records = {item["path"]: item for item in manifest["files"]}
        assert records["deleted.py"]["status"] == "deleted"
        assert records["renamed.py"]["status"] == "deleted"
        assert records["名前変更.py"]["status"] == "included"
        assert records[".env"]["status"] == "excluded"
        assert records["linked.txt"]["status"] == "excluded"
        assert manifest["commands"] == [
            {"command": "python -m pytest", "exit_code": 1, "output": "1 failed"}
        ]
    assert (repository / "changed.py").read_text() == "before = 1\n"


@pytest.mark.anyio
async def test_symlinked_workspace_and_custom_config_are_rejected(
    tmp_path: Path,
) -> None:
    executor = CodexCharacterWorkExecutor(tmp_path, None)
    directory = await executor.prepare_workspace(_task())
    directory.rmdir()
    other = tmp_path / "other"
    other.mkdir()
    directory.symlink_to(other, target_is_directory=True)
    with pytest.raises(CharacterWorkError, match="一致"):
        await executor.prepare_workspace(_task())
    (tmp_path / "codex").mkdir()
    (tmp_path / "codex" / "config.toml").write_text('sandbox_mode="danger-full-access"')
    with pytest.raises(CharacterWorkError, match="config.toml"):
        await executor.runtime_config(other)


@pytest.mark.anyio
@pytest.mark.skipif(sys.platform != "linux", reason="Linux sandbox integration")
async def test_real_sandbox_allows_host_filesystem_and_network_but_keeps_credentials_out(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    executor = CodexCharacterWorkExecutor(tmp_path, None)
    directory = await executor.prepare_workspace(_task())
    (tmp_path / "private.txt").write_text("test-only-canary")
    (directory / ".env").write_text("test-only-canary")
    (directory / "linked.txt").symlink_to(tmp_path / "private.txt")
    outside = tmp_path / "outside-result.txt"
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "test-only-token")
    config = await executor.runtime_config(directory)
    arguments = list(config.launch_args_override or ())
    program = """
import os, pathlib, socket, sys
assert 'DISCORD_BOT_TOKEN' not in os.environ
for path in ['.env', 'linked.txt', '../../../private.txt']:
    pathlib.Path(path).read_text()
pathlib.Path('result.txt').write_text('ok')
pathlib.Path(sys.argv[2]).write_text('outside')
with socket.create_connection(('127.0.0.1', int(sys.argv[1])), timeout=1):
    pass
"""

    async def accept(
        reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(accept, "127.0.0.1", 0)
    async with server:
        port = server.sockets[0].getsockname()[1]
        arguments[-3:] = [
            "sandbox",
            "-P",
            "discord-work",
            "--",
            "/usr/bin/python3",
            "-c",
            program,
            str(port),
            str(outside),
        ]
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            async with asyncio.timeout(15):
                stdout, stderr = await process.communicate()
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()
    assert process.returncode == 0, (stdout + stderr).decode()
    assert (directory / "result.txt").read_text() == "ok"
    assert outside.read_text() == "outside"
