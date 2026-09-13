"""Atomic work records remain outside writable agent directories."""

import os
from dataclasses import replace
from pathlib import Path

import pytest

from app.contracts.messages.character_work import CharacterWork, CharacterWorkError
from app.infrastructure.codex.work_store import FileCharacterWorkStore


@pytest.mark.anyio
async def test_round_trip_and_failed_replace_preserves_previous_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = FileCharacterWorkStore(tmp_path / "tasks")
    task = CharacterWork("100", "456", "123", "2", "lilia", "調査", "100")
    await store.save(task)
    assert await store.list_tasks() == [task]

    def fail_replace(source: str, target: Path) -> None:
        raise OSError("disk unavailable")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(CharacterWorkError, match="保存"):
        await store.save(replace(task, status="completed", result="結果"))
    assert await store.list_tasks() == [task]
    assert not list((tmp_path / "tasks").glob("*.tmp"))
    with pytest.raises(CharacterWorkError, match="ID"):
        await store.save(replace(task, id="../escape"))


@pytest.mark.anyio
async def test_corrupt_state_is_not_silently_discarded(tmp_path: Path) -> None:
    (tmp_path / "100.json").write_text('{"partial":', encoding="utf-8")
    with pytest.raises(CharacterWorkError, match="読み込"):
        await FileCharacterWorkStore(tmp_path).list_tasks()


@pytest.mark.anyio
async def test_recent_reviewed_work_is_scoped_and_limited(tmp_path: Path) -> None:
    store = FileCharacterWorkStore(tmp_path)
    tasks = (
        CharacterWork(
            "1",
            "456",
            "123",
            "2",
            "lilia",
            "old",
            "1",
            status="completed",
            review="old review",
        ),
        CharacterWork(
            "2",
            "456",
            "123",
            "2",
            "lilia",
            "new",
            "2",
            status="completed",
            review="new review",
        ),
        CharacterWork(
            "3",
            "456",
            "123",
            "2",
            "lilia",
            "newest",
            "3",
            status="completed",
            review="newest review",
        ),
        CharacterWork(
            "4",
            "456",
            "123",
            "2",
            "lilia",
            "running",
            "4",
            status="running",
            review="not complete",
        ),
        CharacterWork(
            "5",
            "999",
            "123",
            "2",
            "lilia",
            "other",
            "5",
            status="completed",
            review="other channel",
        ),
        CharacterWork(
            "6",
            "456",
            "123",
            "2",
            "lilia",
            "times",
            "6",
            status="completed",
            review="times work",
            origin="times",
        ),
    )
    for task in tasks:
        await store.save(task)

    result = await store.recent_reviewed_work("456", "123", "2", limit=2)

    assert [task.id for task in result] == ["3", "2"]
    assert await store.recent_reviewed_work("456", "123", "2", limit=0) == []
