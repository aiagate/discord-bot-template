"""Durability, ownership, cancellation, and resumption of character work."""

import asyncio
from collections.abc import AsyncGenerator
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from flow_res import is_err, is_ok

from app.application.character_settings import load_ai_maid_definitions
from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkArtifacts,
    WorkAttachment,
    WorkEvent,
)
from app.contracts.ports.character_work import ICharacterWorkExecutor
from app.infrastructure.codex.work_store import FileCharacterWorkStore
from app.usecases.chat.character_work import CharacterWorkService, WorkResult


class ControlledExecutor(ICharacterWorkExecutor):
    """Model execution controlled by test events, with no network access."""

    def __init__(self) -> None:
        self.calls: list[CharacterWork] = []
        self.instructions: list[str] = []
        self.inputs: list[tuple[str, str]] = []
        self.events: dict[str, asyncio.Queue[WorkEvent | Exception]] = {}
        self.ready = asyncio.Event()
        self.closed: list[str] = []
        self.closing = asyncio.Event()
        self.close_gate: asyncio.Event | None = None

    async def run(
        self, task: CharacterWork, instructions: str
    ) -> AsyncGenerator[WorkEvent]:
        """Expose a saved session before accepting further model events."""
        self.calls.append(task)
        self.instructions.append(instructions)
        queue: asyncio.Queue[WorkEvent | Exception] = asyncio.Queue()
        self.events[task.id] = queue
        try:
            yield WorkEvent("session", thread_id="thread-" + task.id, cwd="/work")
            self.ready.set()
            while True:
                event = await queue.get()
                if isinstance(event, Exception):
                    raise event
                yield event
                if event.kind in {"completed", "stopped"}:
                    return
        finally:
            self.closing.set()
            if self.close_gate is not None:
                await self.close_gate.wait()
            self.closed.append(task.id)

    async def steer(self, task_id: str, prompt: str) -> bool:
        """Record an accepted live instruction."""
        if task_id not in self.events:
            return False
        self.inputs.append((task_id, prompt))
        return True

    async def attachments(self, task: CharacterWork) -> tuple[WorkAttachment, ...]:
        """Return no files for these orchestration-only tests."""
        return ()


def _service(
    tmp_path: Path, *, timeout: float = 10
) -> tuple[CharacterWorkService, ControlledExecutor, FileCharacterWorkStore, AsyncMock]:
    store = FileCharacterWorkStore(tmp_path / "tasks")
    executor = ControlledExecutor()
    update = AsyncMock()
    service = CharacterWorkService(
        store,
        executor,
        load_ai_maid_definitions(),
        on_update=update,
        timeout_seconds=timeout,
    )
    return service, executor, store, update


async def _start(
    service: CharacterWorkService, *, message: str = "100", owner: str = "2"
) -> WorkResult:
    return await service.start(
        guild_id="456",
        channel_id="123",
        owner_id=owner,
        message_id=message,
        character_id="lilia",
        prompt="新しい仕様を調べて",
    )


async def _follow(
    service: CharacterWorkService, *, message: str = "101", owner: str = "2"
) -> WorkResult:
    return await service.follow_up(
        guild_id="456",
        channel_id="123",
        owner_id=owner,
        message_id=message,
        prompt="公式資料を優先して",
    )


async def _ready(executor: ControlledExecutor) -> None:
    async with asyncio.timeout(3):
        await executor.ready.wait()
    executor.ready.clear()


async def _finish(service: CharacterWorkService) -> None:
    async with asyncio.timeout(3):
        await asyncio.gather(*service._active.values())


@pytest.mark.anyio
async def test_start_steer_complete_and_resume_same_session(tmp_path: Path) -> None:
    service, executor, store, update = _service(tmp_path)
    try:
        result = await _start(service)
        assert is_ok(result)
        await _ready(executor)
        records = await store.list_tasks()
        assert records[0].thread_id == "thread-100"
        assert records[0].status == "running"
        assert is_ok(await _follow(service))
        assert is_ok(await _follow(service))
        assert executor.inputs == [("100", "公式資料を優先して")]
        await executor.events["100"].put(WorkEvent("completed", text="出典と調査結果"))
        await _finish(service)
        current = service.current("456", "123", "2")
        assert current is not None and current.status == "completed"
        assert current.last_message_id == "101"
        assert current.result == "出典と調査結果"
        assert update.await_args is not None
        assert update.await_args.args[0].status == "completed"

        assert is_ok(await _follow(service, message="102"))
        await _ready(executor)
        assert executor.calls[1].thread_id == "thread-100"
        assert executor.calls[1].prompt == "公式資料を優先して"
        assert "Lilia" in executor.instructions[0]
        assert "出典URL" in executor.instructions[0]
    finally:
        await service.close()
    assert executor.closed == ["100", "100"]


@pytest.mark.anyio
async def test_duplicates_and_other_owners_cannot_control_work(tmp_path: Path) -> None:
    service, executor, _, _ = _service(tmp_path)
    try:
        assert is_ok(await _start(service))
        await _ready(executor)
        assert is_ok(await _start(service))
        assert is_err(await _start(service, owner="3"))
        assert is_err(await _follow(service, owner="3"))
        assert is_err(await service.stop("456", "124", "2"))
        assert service.current("456", "123", "3") is None
        assert len(executor.calls) == 1
        assert is_err(await _start(service, message="102"))
        assert is_ok(await _start(service, message="103", owner="3"))
        assert is_err(await _start(service, message="104", owner="4"))
    finally:
        await service.close()


@pytest.mark.anyio
async def test_save_failure_prevents_execution(tmp_path: Path) -> None:
    service, executor, store, _ = _service(tmp_path)
    store.save = AsyncMock(side_effect=CharacterWorkError("保存失敗"))
    assert is_err(await _start(service))
    assert not service._active
    assert executor.calls == []


@pytest.mark.anyio
async def test_restart_pauses_without_replaying_and_preserves_result(
    tmp_path: Path,
) -> None:
    service, executor, store, _ = _service(tmp_path)
    record = CharacterWork(
        "100",
        "456",
        "123",
        "2",
        "lilia",
        "最初の依頼",
        "101",
        status="running",
        thread_id="saved-thread",
        cwd="/work",
        result="前の結果",
    )
    await store.save(record)
    await service.initialize()
    current = service.current("456", "123", "2")
    assert current is not None and current.status == "paused"
    assert current.result == "前の結果"
    assert executor.calls == []
    assert is_ok(await _follow(service, message="102"))
    await _ready(executor)
    assert executor.calls[0].thread_id == "saved-thread"
    await service.close()


@pytest.mark.anyio
async def test_stop_before_executor_starts_and_chat_unlinks(tmp_path: Path) -> None:
    service, executor, _, _ = _service(tmp_path)
    assert is_ok(await _start(service))
    assert is_ok(await service.stop("456", "123", "2", unlink=True))
    assert service.current("456", "123", "2") is None
    assert not service._active
    assert is_err(await _follow(service))
    assert executor.calls == []
    assert is_ok(await _start(service, message="102"))
    await service.close()


@pytest.mark.anyio
async def test_stop_rejects_racing_followup_until_runtime_closes(
    tmp_path: Path,
) -> None:
    service, executor, _, _ = _service(tmp_path)
    await _start(service)
    await _ready(executor)
    gate = asyncio.Event()
    executor.close_gate = gate
    stopping = asyncio.create_task(service.stop("456", "123", "2"))
    async with asyncio.timeout(3):
        await executor.closing.wait()
    assert is_err(await _follow(service))
    assert is_err(await service.stop("456", "123", "2"))
    gate.set()
    assert is_ok(await stopping)
    assert is_ok(await _follow(service))
    await _ready(executor)
    await service.close()


@pytest.mark.anyio
@pytest.mark.parametrize("failure", [False, True])
async def test_failed_or_timed_out_work_closes_executor(
    tmp_path: Path, failure: bool
) -> None:
    service, executor, _, _ = _service(tmp_path, timeout=0.1 if not failure else 10)
    await _start(service)
    await _ready(executor)
    if failure:
        await executor.events["100"].put(RuntimeError("private provider details"))
    await _finish(service)
    current = service.current("456", "123", "2")
    assert current is not None and current.status == "failed"
    assert "private" not in current.summary
    assert executor.closed == ["100"]
    assert is_ok(await _follow(service))
    await service.close()


@pytest.mark.anyio
async def test_discord_failure_does_not_lose_completed_result(tmp_path: Path) -> None:
    service, executor, store, update = _service(tmp_path)
    artifacts = WorkArtifacts("100", "test-digest", 10, 1, "検証結果")

    async def deliver(task: CharacterWork) -> None:
        if task.status == "completed":
            assert (await store.list_tasks())[0].artifacts == artifacts
            raise RuntimeError("Discord offline")

    update.side_effect = deliver
    await _start(service)
    await _ready(executor)
    await executor.events["100"].put(
        WorkEvent("completed", text="結果", artifacts=artifacts)
    )
    await _finish(service)
    assert (await store.list_tasks())[0].result == "結果"
    assert (await store.list_tasks())[0].status == "completed"
    assert (await store.list_tasks())[0].artifacts == artifacts


@pytest.mark.anyio
async def test_shutdown_during_result_delivery_preserves_completion(
    tmp_path: Path,
) -> None:
    service, executor, store, update = _service(tmp_path)
    delivering = asyncio.Event()

    async def deliver(task: CharacterWork) -> None:
        if task.status == "completed":
            delivering.set()
            await asyncio.Event().wait()

    update.side_effect = deliver
    await _start(service)
    await _ready(executor)
    await executor.events["100"].put(WorkEvent("completed", text="保存された結果"))
    async with asyncio.timeout(3):
        await delivering.wait()
    await service.close()
    record = (await store.list_tasks())[0]
    assert record.status == "completed" and record.result == "保存された結果"


@pytest.mark.anyio
async def test_shutdown_during_result_save_waits_and_keeps_new_result(
    tmp_path: Path,
) -> None:
    service, executor, store, _ = _service(tmp_path)
    saving = asyncio.Event()
    release = asyncio.Event()
    save = store.save

    async def delayed_save(task: CharacterWork) -> None:
        if task.status == "completed":
            saving.set()
            await release.wait()
        await save(task)

    store.save = AsyncMock(side_effect=delayed_save)
    await _start(service)
    await _ready(executor)
    await executor.events["100"].put(WorkEvent("completed", text="最新の結果"))
    async with asyncio.timeout(3):
        await saving.wait()
    closing = asyncio.create_task(service.close())
    await asyncio.sleep(0)
    release.set()
    await closing
    record = (await store.list_tasks())[0]
    assert record.status == "completed" and record.result == "最新の結果"


@pytest.mark.anyio
async def test_unknown_characters_and_invalid_inputs_are_rejected(
    tmp_path: Path,
) -> None:
    service, _, store, _ = _service(tmp_path)
    request = {
        "guild_id": "456",
        "channel_id": "123",
        "owner_id": "2",
        "message_id": "100",
    }
    assert is_err(await service.start(**request, character_id="unknown", prompt="修正"))
    assert is_err(await service.start(**request, character_id="lilia", prompt=""))
    request["message_id"] = "../escape"
    assert is_err(await service.start(**request, character_id="lilia", prompt="調査"))
    await store.save(CharacterWork("100", "456", "123", "2", "lilia", "a", "100"))
    await store.save(replace((await store.list_tasks())[0], id="101", linked=False))
    await service.initialize()
    assert service.current("456", "123", "2") is None


@pytest.mark.anyio
@pytest.mark.parametrize(
    "character_id",
    [character.character_id for character in load_ai_maid_definitions().characters],
)
async def test_every_registered_character_can_research_and_code(
    tmp_path: Path,
    character_id: str,
) -> None:
    service, executor, _, _ = _service(tmp_path)
    character = next(
        item for item in service._roster.characters if item.character_id == character_id
    )
    try:
        result = await service.start(
            guild_id="456",
            channel_id="123",
            owner_id="2",
            message_id="100",
            character_id=character_id,
            prompt="資料を調べて検証コードを作って",
        )
        assert is_ok(result)
        await _ready(executor)
        assert executor.calls[0].character_id == character_id
        instructions = executor.instructions[0]
        assert character.name in instructions
        assert character.persona in instructions
        assert character.speech_style in instructions
        assert "全員が調査・コーディング・文書作成・検証を行えます" in instructions
        assert "出典URL" in instructions and "コードのテスト" in instructions
    finally:
        await service.close()
