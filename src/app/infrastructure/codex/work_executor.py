"""Run character tasks with the pinned Codex Python SDK."""

import asyncio
import json
import logging
import os
import re
import shutil
from collections.abc import AsyncGenerator
from pathlib import Path

from codex_cli_bin import bundled_codex_path, bundled_path_dir
from openai_codex import ApprovalMode, AsyncCodex, AsyncTurnHandle, CodexConfig
from openai_codex.errors import InvalidRequestError
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    CommandExecutionThreadItem,
    ItemCompletedNotification,
    ItemStartedNotification,
    MessagePhase,
    ReasoningEffort,
    TurnCompletedNotification,
    TurnStatus,
)

from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkAttachment,
    WorkCommandEvidence,
    WorkEvent,
)
from app.contracts.ports.character_work import ICharacterWorkExecutor
from app.infrastructure.codex.work_artifacts import FileWorkArtifacts

logger = logging.getLogger(__name__)
MAX_TOOL_CALLS = 100


def _process_environment() -> dict[str, str]:
    return {
        key: value
        for key, value in os.environ.items()
        if key in {"PATH", "HOME", "LANG", "SYSTEMROOT", "WINDIR"}
    }


async def _git(directory: Path, *arguments: str) -> str:
    process = await asyncio.create_subprocess_exec(
        "git",
        "-C",
        str(directory),
        *arguments,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
        env=_process_environment(),
    )
    try:
        async with asyncio.timeout(30):
            stdout, _ = await process.communicate()
    finally:
        if process.returncode is None:
            process.kill()
            await process.wait()
    if process.returncode != 0:
        raise CharacterWorkError("作業用リポジトリの準備に失敗しました。")
    return stdout.decode().strip()


class CodexCharacterWorkExecutor(ICharacterWorkExecutor):
    """Give each running task its own runtime and resumable conversation."""

    def __init__(
        self,
        root: Path,
        repository: Path | None,
        model: str | None = None,
        reasoning_effort: str | None = None,
    ) -> None:
        self._root = root.resolve()
        self._repository = repository.resolve() if repository is not None else None
        self._model = model
        self._reasoning_effort = (
            ReasoningEffort(reasoning_effort) if reasoning_effort is not None else None
        )
        self._turns: dict[str, AsyncTurnHandle] = {}
        self._artifacts = FileWorkArtifacts(self._root)

    async def prepare_workspace(self, task: CharacterWork) -> Path:
        """Create an isolated directory or Git worktree for any character."""
        if (
            re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", task.character_id) is None
            or not task.id.isascii()
            or not task.id.isdecimal()
            or len(task.id) > 20
        ):
            raise CharacterWorkError("作業の担当またはIDが不正です。")
        directory = self._root / "workspaces" / task.character_id / task.id
        if directory.resolve() != directory or (
            task.cwd is not None and Path(task.cwd) != directory
        ):
            raise CharacterWorkError("保存された作業場所が設定と一致しません。")
        if task.thread_id is not None and not directory.is_dir():
            raise CharacterWorkError("再開する作業場所が見つかりません。")
        directory.parent.mkdir(parents=True, exist_ok=True)
        if not directory.exists():
            if self._repository is None:
                directory.mkdir()
            else:
                await _git(
                    self._repository,
                    "worktree",
                    "add",
                    "-b",
                    f"codex/{task.character_id}-{task.id}",
                    str(directory),
                    "HEAD",
                )
        if (directory / ".git").exists():
            if self._repository is None:
                raise CharacterWorkError("この作業のリポジトリが未設定です。")
            toplevel = await _git(directory, "rev-parse", "--show-toplevel")
            common = await _git(directory, "rev-parse", "--git-common-dir")
            expected = await _git(self._repository, "rev-parse", "--git-common-dir")
            if (
                Path(toplevel).resolve() != directory
                or (directory / common).resolve()
                != (self._repository / expected).resolve()
            ):
                raise CharacterWorkError("作業場所が設定されたリポジトリと異なります。")
        return directory

    async def runtime_config(self, directory: Path) -> CodexConfig:
        """Confine file access and keep bot credentials out of subprocesses."""
        codex_directory = self._root / "codex"
        codex_directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        if (codex_directory / "config.toml").exists():
            raise CharacterWorkError(
                "作業用Codexのconfig.tomlを取り除いてください。実行設定はBotが管理します。"
            )
        temporary = directory / ".tmp"
        temporary.mkdir(exist_ok=True)
        binary = bundled_codex_path()
        bundled_tools = bundled_path_dir()
        filesystem = [
            '":root"="deny"',
            '":minimal"="read"',
            '":workspace_roots"={"."="write",".git"="read",'
            '".codex"="read",".agents"="read","**/.env*"="deny"}',
            f'{json.dumps(str(binary.parent))}="read"',
        ]
        if bundled_tools is not None:
            filesystem.append(f'{json.dumps(str(bundled_tools))}="read"')
        if self._repository is not None and (directory / ".git").exists():
            common = (
                directory / await _git(directory, "rev-parse", "--git-common-dir")
            ).resolve()
            filesystem.append(f'{json.dumps(str(common))}="read"')
        overrides = [
            'default_permissions="discord-work"',
            "permissions={discord-work={filesystem={"
            + ",".join(filesystem)
            + "},network={enabled=false}}}",
            'shell_environment_policy.inherit="none"',
            "shell_environment_policy.ignore_default_excludes=false",
            "shell_environment_policy.experimental_use_profile=false",
            f"shell_environment_policy.set.PATH={json.dumps(os.environ.get('PATH', ''))}",
            f"shell_environment_policy.set.TMPDIR={json.dumps(str(temporary))}",
            f"shell_environment_policy.set.HOME={json.dumps(str(directory))}",
            'shell_environment_policy.set.LANG="C.UTF-8"',
            "features.apps=false",
            "features.plugins=false",
            'web_search="live"',
            f'projects={{{json.dumps(str(directory))}={{trust_level="untrusted"}}}}',
        ]
        environment = _process_environment()
        environment.update(
            CODEX_HOME=str(codex_directory),
            HOME=str(codex_directory),
            TMPDIR=str(temporary),
        )
        if bundled_tools is not None:
            environment["PATH"] = (
                f"{bundled_tools}{os.pathsep}{environment.get('PATH', '')}"
            )
        launcher = shutil.which("env")
        if launcher is None:
            raise CharacterWorkError("作業機能にはLinuxのenvコマンドが必要です。")
        # The SDK merges the parent environment; env -i removes it before Codex runs.
        arguments = [launcher, "-i"]
        arguments.extend(f"{key}={value}" for key, value in environment.items())
        arguments.append(str(binary))
        for override in overrides:
            arguments.extend(("--config", override))
        arguments.extend(("app-server", "--listen", "stdio://"))
        return CodexConfig(
            cwd=str(directory),
            launch_args_override=tuple(arguments),
            client_name="discord_character_work",
            client_title="Discord character work",
            experimental_api=False,
        )

    async def run(
        self, task: CharacterWork, instructions: str
    ) -> AsyncGenerator[WorkEvent]:
        """Persistable session identity precedes all model execution."""
        directory = await self.prepare_workspace(task)
        uses_repository = (directory / ".git").exists()
        config = await self.runtime_config(directory)
        client = AsyncCodex(config)
        turn: AsyncTurnHandle | None = None
        finished = False
        terminal: WorkEvent | None = None
        commands: list[WorkCommandEvidence] = []
        try:
            if task.thread_id is None:
                thread = await client.thread_start(
                    cwd=str(directory),
                    model=self._model,
                    approval_mode=ApprovalMode.deny_all,
                    developer_instructions=instructions,
                )
            else:
                thread = await client.thread_resume(
                    task.thread_id,
                    cwd=str(directory),
                    model=self._model,
                    approval_mode=ApprovalMode.deny_all,
                    developer_instructions=instructions,
                )
            yield WorkEvent("session", thread_id=thread.id, cwd=str(directory))
            if self._reasoning_effort is None:
                turn = await thread.turn(task.prompt)
            else:
                turn = await thread.turn(task.prompt, effort=self._reasoning_effort)
            self._turns[task.id] = turn
            result = ""
            fallback = ""
            tool_calls = 0
            async for event in turn.stream():
                payload = event.payload
                if isinstance(payload, ItemStartedNotification):
                    kind = payload.item.root.type
                    progress = {
                        "webSearch": "資料を調べています。",
                        "commandExecution": "コマンドを実行しています。",
                        "fileChange": "ファイルを編集しています。",
                    }.get(kind)
                    if progress is not None:
                        tool_calls += 1
                        if tool_calls > MAX_TOOL_CALLS:
                            raise CharacterWorkError(
                                "操作回数の上限で作業を中断しました。"
                            )
                        yield WorkEvent("progress", text=progress)
                elif isinstance(payload, ItemCompletedNotification):
                    item = payload.item.root
                    if isinstance(item, CommandExecutionThreadItem):
                        if len(commands) < MAX_TOOL_CALLS:
                            commands.append(
                                WorkCommandEvidence(
                                    item.command[:2000],
                                    item.exit_code,
                                    (item.aggregated_output or "")[-4000:],
                                )
                            )
                    elif isinstance(item, AgentMessageThreadItem):
                        if item.phase == MessagePhase.final_answer:
                            result = item.text
                        elif item.phase is None:
                            fallback = item.text
                        elif item.text.strip():
                            yield WorkEvent("progress", text=item.text[:2000])
                elif isinstance(payload, TurnCompletedNotification):
                    finished = True
                    if payload.turn.status == TurnStatus.interrupted:
                        terminal = WorkEvent("stopped", text="作業を中止しました。")
                    elif payload.turn.status == TurnStatus.completed:
                        text = (result or fallback).strip()
                        if not text:
                            raise CharacterWorkError("作業結果を取得できませんでした。")
                        terminal = WorkEvent("completed", text=text[:32000])
                    else:
                        raise CharacterWorkError("Codexの作業が失敗しました。")
                    break
            if terminal is None:
                raise CharacterWorkError("作業の完了通知を受信できませんでした。")
        finally:
            self._turns.pop(task.id, None)
            if turn is not None and not finished:
                try:
                    async with asyncio.timeout(5):
                        await turn.interrupt()
                except Exception:
                    logger.warning(
                        "Could not interrupt work %s before closing runtime", task.id
                    )
            await client.close()
        if terminal.kind == "completed":
            changes = (
                await self._changed_files(directory, config)
                if uses_repository
                else None
            )
            artifacts = await self._artifacts.collect(
                task,
                directory,
                changes,
                tuple(commands),
                terminal.text,
            )
            terminal = WorkEvent("completed", terminal.text, artifacts=artifacts)
        yield terminal

    async def _changed_files(
        self, directory: Path, config: CodexConfig
    ) -> list[tuple[str, str]]:
        if config.launch_args_override is None:
            raise CharacterWorkError("成果収集用のサンドボックスがありません。")
        arguments = [
            *config.launch_args_override[:-3],
            "sandbox",
            "-P",
            "discord-work",
            "--",
            "git",
            "--no-optional-locks",
            "-c",
            "core.fsmonitor=false",
            "status",
            "--porcelain=v1",
            "-z",
            "--untracked-files=all",
            "--no-renames",
        ]
        process = await asyncio.create_subprocess_exec(
            *arguments,
            cwd=directory,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
        )
        try:
            async with asyncio.timeout(30):
                assert process.stdout is not None
                output = bytearray()
                while chunk := await process.stdout.read(65536):
                    output.extend(chunk)
                    if len(output) > 1024 * 1024:
                        raise CharacterWorkError(
                            "成果一覧が大きすぎます。作業を分割してください。"
                        )
                await process.wait()
            if process.returncode != 0:
                raise CharacterWorkError("変更ファイルの一覧を取得できませんでした。")
            return [
                (item[3:], "deleted" if "D" in item[:2] else "changed")
                for item in output.decode("utf-8").split("\0")
                if item
            ]
        finally:
            if process.returncode is None:
                process.kill()
                await process.wait()

    async def attachments(self, task: CharacterWork) -> tuple[WorkAttachment, ...]:
        """Read the verified snapshot, including after the runtime has exited."""
        return await self._artifacts.load(task)

    async def steer(self, task_id: str, prompt: str) -> bool:
        """Send follow-up input only to this task's currently running turn."""
        turn = self._turns.get(task_id)
        if turn is None:
            return False
        try:
            async with asyncio.timeout(10):
                await turn.steer(prompt)
            return True
        except InvalidRequestError:
            return False
