"""A5-A7: rollback, owned projections, guidance budget, and real child supervision."""

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import cast

import pytest

from app.contracts.messages.collective import Memory
from app.infrastructure.collective.codex import CodexWorker
from app.infrastructure.collective.codex_process import process_start
from app.infrastructure.collective.store import SQLiteCollectiveStore
from app.infrastructure.collective.workspace import CharacterWorkspaces
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import CodexDouble
from tests.collective.test_runtime import finished, start_activity


def test_sqlite_transaction_rolls_back_and_lock_excludes_second_runner(
    tmp_path: Path,
) -> None:
    store = SQLiteCollectiveStore(tmp_path)
    with pytest.raises(RuntimeError), store.transaction() as state:
        state.memories["alice/n"] = Memory(
            owner="alice",
            note_id="n",
            kind="fact",
            section="profile",
            content="rollback",
            sources=["s"],
        )
        raise RuntimeError("failed")
    assert not store.read().memories
    with (
        store.lock(),
        pytest.raises(RuntimeError),
        SQLiteCollectiveStore(tmp_path).lock(),
    ):
        pass
    with store.lock():
        pass


@pytest.mark.anyio
async def test_projection_recovers_tampering_deletion_and_moved_artifacts(
    collective: Collective,
) -> None:
    await start_activity(collective)
    collective.schedule(2)
    codex = cast(CodexDouble, collective.codex)
    codex.results.append(finished())
    await collective.work_step(2)
    context = codex.contexts[0]
    workspace = context.workspace
    (workspace / "memory" / "stale.md").write_text("old")
    artifact = workspace / "tasks" / "current.txt"
    artifact.write_text("result")
    adapter = cast(CharacterWorkspaces, collective.workspaces)
    adapter.prepare(context, collective.store.read())
    assert not (workspace / "memory" / "stale.md").exists()
    assert "current.txt" in (workspace / "workspace-index.md").read_text()
    artifact.rename(workspace / "tasks" / "renamed.txt")
    (workspace / "AGENTS.md").write_text("x" * 50000)
    adapter.prepare(context, collective.store.read())
    guide = (workspace / "AGENTS.md").read_text()
    assert "sources.json" in guide and "AGY" in guide
    archived = list((workspace / "guide-history").glob("*.md"))
    assert any(path.stat().st_size == 50000 for path in archived)
    assert "guide-history/" in guide
    adapter.prepare(context, collective.store.read())
    assert list((workspace / "guide-history").glob("*.md")) == archived
    assert "current.txt" not in (workspace / "workspace-index.md").read_text()
    assert "renamed.txt" in (workspace / "workspace-index.md").read_text()
    adapter.guide_bytes = 10
    with pytest.raises(ValueError, match="Combined"):
        adapter.prepare(context, collective.store.read())
    adapter.guide_bytes = 32768
    (workspace / "AGENTS.override.md").write_text("hidden")
    with pytest.raises(ValueError, match="hides required"):
        adapter.prepare(context, collective.store.read())


@pytest.mark.anyio
async def test_real_supervisor_reaps_detached_children(tmp_path: Path) -> None:
    manifest = tmp_path / "process.json"
    child_file = tmp_path / "child.txt"
    script = tmp_path / "spawn.py"
    script.write_text(
        "import subprocess, sys, time\n"
        "from pathlib import Path\n"
        "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'], start_new_session=True)\n"
        f"Path({str(child_file)!r}).write_text(str(child.pid))\n"
        "time.sleep(60)\n"
    )
    process = await asyncio.create_subprocess_exec(
        sys.executable,
        "-m",
        "app.infrastructure.collective.codex_process",
        str(manifest),
        sys.executable,
        str(script),
        stdout=asyncio.subprocess.DEVNULL,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        for _ in range(100):
            if child_file.exists():
                break
            await asyncio.sleep(0.02)
        assert child_file.exists()
        child_pid = int(child_file.read_text())
        worker = CodexWorker(tmp_path / "SKILL.md")
        assert await worker.recover({"process_file": str(manifest)})
        await asyncio.wait_for(process.wait(), 5)
        assert json.loads(manifest.read_text())["finished"]
        assert process_start(child_pid) is None
    finally:
        if process.returncode is None:
            process.terminate()
            await process.wait()


@pytest.mark.anyio
async def test_recovery_does_not_signal_recycled_pid(tmp_path: Path) -> None:
    manifest = tmp_path / "process.json"
    manifest.write_text(
        json.dumps({"pid": os.getpid(), "start": "impossible", "finished": False})
    )
    worker = CodexWorker(tmp_path / "SKILL.md")
    assert not await worker.recover({"process_file": str(manifest)})
    assert not await worker.recover({"process_file": str(tmp_path / "missing")})
    assert await worker.recover({})
