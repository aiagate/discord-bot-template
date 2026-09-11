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
