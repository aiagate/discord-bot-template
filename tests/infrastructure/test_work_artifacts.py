"""Verify actual file snapshots, exclusions, limits, and durable retrieval."""

import hashlib
import io
import json
import os
import zipfile
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkCommandEvidence,
)
from app.infrastructure.codex import work_artifacts
from app.infrastructure.codex.work_artifacts import FileWorkArtifacts
from app.infrastructure.codex.work_executor import CodexCharacterWorkExecutor


def _workspace(root: Path) -> tuple[CharacterWork, Path, FileWorkArtifacts]:
    task = CharacterWork("100", "456", "123", "2", "lilia", "調査", "101")
    directory = root / "workspaces" / "lilia" / task.id
    directory.mkdir(parents=True)
    return task, directory, FileWorkArtifacts(root)


def _manifest(data: bytes) -> dict[str, Any]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return json.loads(archive.read("manifest.json"))


@pytest.mark.anyio
async def test_actual_bytes_syntax_and_command_evidence_survive_workspace_changes(
    tmp_path: Path,
) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    contents = {
        "code.py": b"answer = 42\n",
        "broken.py": b"def broken(\n",
        "data.json": b'{"ok": true}',
        "broken.json": b"{",
        "config.toml": b"value = 1",
        "broken.toml": b"[",
        "調査メモ.md": "出典: https://example.invalid/docs\n".encode(),
    }
    for path, content in contents.items():
        (directory / path).write_bytes(content)
    evidence = (
        WorkCommandEvidence("python -m pytest", 1, "1 failed"),
        WorkCommandEvidence("python code.py", 0, "42"),
        WorkCommandEvidence("unconfirmed", None, ""),
    )
    snapshot = await artifacts.collect(task, directory, None, evidence, "調査結果")
    completed = replace(task, artifacts=snapshot)
    (attachment,) = await artifacts.load(completed)
    assert snapshot.file_count == len(contents)
    assert snapshot.sha256 == hashlib.sha256(attachment.data).hexdigest()
    assert "成功3件・失敗3件" in snapshot.summary
    assert "非0終了1件・未確定1件" in snapshot.summary
    manifest = _manifest(attachment.data)
    assert manifest["commands"][0]["output"] == "1 failed"
    assert manifest["commands"][0]["exit_code"] == 1
    assert manifest["revision_id"] == "101"
    with zipfile.ZipFile(io.BytesIO(attachment.data)) as archive:
        assert archive.read("report.md").decode() == "調査結果"
        for path, content in contents.items():
            assert archive.read("files/" + path) == content
    (directory / "code.py").write_text("changed after publication")
    assert await FileWorkArtifacts(tmp_path).load(completed) == (attachment,)
    with pytest.raises(CharacterWorkError, match="保存"):
        await artifacts.collect(task, directory, None, (), "overwrite")
    assert await artifacts.load(completed) == (attachment,)
    newer = await artifacts.collect(
        replace(task, last_message_id="102"), directory, None, (), "追記"
    )
    assert newer.revision_id == "102" and newer.sha256 != snapshot.sha256


@pytest.mark.anyio
async def test_links_secrets_and_special_files_are_excluded(tmp_path: Path) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    outside = tmp_path / "outside.txt"
    outside.write_text("private canary")
    (directory / "file-link").symlink_to(outside)
    (directory / "dir-link").symlink_to(tmp_path, target_is_directory=True)
    os.link(outside, directory / "hard-link")
    os.mkfifo(directory / "fifo")
    for path in [".env", ".ENV.local", "auth.json", "key.pem", "id_ed25519"]:
        (directory / path).write_text("private canary")
    for name in [".CODEX", "node_modules", ".ssh"]:
        (directory / name).mkdir()
        (directory / name / "private.txt").write_text("private canary")
    (directory / "memo.md").write_text("public memo")
    snapshot = await artifacts.collect(task, directory, None, (), "done")
    (attachment,) = await artifacts.load(replace(task, artifacts=snapshot))
    manifest = _manifest(attachment.data)
    assert snapshot.file_count == 1
    assert len(manifest["files"]) == 13
    assert all(
        record["status"] == "excluded" or record["path"] == "memo.md"
        for record in manifest["files"]
    )
    with zipfile.ZipFile(io.BytesIO(attachment.data)) as archive:
        assert archive.namelist() == ["report.md", "manifest.json", "files/memo.md"]
        assert b"private canary" not in b"".join(
            archive.read(name) for name in archive.namelist()
        )


@pytest.mark.anyio
async def test_changed_files_deleted_paths_and_traversal(tmp_path: Path) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    (directory / "changed.py").write_text("ok = 1")
    (directory / "unchanged.py").write_text("original = 1")
    changes = [
        ("changed.py", "changed"),
        ("deleted.py", "deleted"),
        ("../outside.txt", "changed"),
        (str(tmp_path / "outside.txt"), "changed"),
        ("a\\b.py", "changed"),
        ("a/./b.py", "changed"),
        ("a\nb.py", "changed"),
    ]
    snapshot = await artifacts.collect(task, directory, changes, (), "done")
    (attachment,) = await artifacts.load(replace(task, artifacts=snapshot))
    records = {item["path"]: item for item in _manifest(attachment.data)["files"]}
    assert records["changed.py"]["status"] == "included"
    assert records["deleted.py"]["status"] == "deleted"
    assert sum(item["status"] == "excluded" for item in records.values()) == 5
    assert "unchanged.py" not in records
    assert snapshot.file_count == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "limit,value,included",
    [("MAX_FILE_BYTES", 2, 0), ("MAX_TOTAL_BYTES", 4, 1), ("MAX_FILES", 1, 1)],
)
async def test_size_and_count_limits_are_reported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    limit: str,
    value: int,
    included: int,
) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    (directory / "a.txt").write_text("abc")
    (directory / "b.txt").write_text("def")
    monkeypatch.setattr(work_artifacts, limit, value)
    snapshot = await artifacts.collect(task, directory, None, (), "done")
    (attachment,) = await artifacts.load(replace(task, artifacts=snapshot))
    assert snapshot.file_count == included
    assert (
        sum(
            item["status"] == "excluded" for item in _manifest(attachment.data)["files"]
        )
        == 2 - included
    )


@pytest.mark.anyio
@pytest.mark.parametrize("scan", [True, False])
async def test_candidate_limit_fails_without_partial_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    scan: bool,
) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    for name in ["a.txt", "b.txt"]:
        (directory / name).write_text("result")
    monkeypatch.setattr(work_artifacts, "MAX_CANDIDATES", 1)
    with pytest.raises(CharacterWorkError, match="多すぎ"):
        await artifacts.collect(
            task,
            directory,
            None if scan else [("a.txt", "changed"), ("b.txt", "changed")],
            (),
            "done",
        )
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.anyio
async def test_archive_limit_and_workspace_scope_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    with pytest.raises(CharacterWorkError, match="作業場所"):
        await artifacts.collect(task, tmp_path, None, (), "done")
    with pytest.raises(CharacterWorkError, match="ID"):
        await artifacts.collect(replace(task, id="../100"), directory, None, (), "done")
    monkeypatch.setattr(work_artifacts, "MAX_ARCHIVE_BYTES", 1)
    with pytest.raises(CharacterWorkError, match="成果ZIP"):
        await artifacts.collect(task, directory, None, (), "done")


@pytest.mark.anyio
@pytest.mark.parametrize(
    "character_id",
    ["", "..", "../noa", "/tmp", "a/b", "a\\b", ".git", "a\nb", "a" * 65],
)
async def test_character_paths_cannot_escape_workspace(
    tmp_path: Path,
    character_id: str,
) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    task = replace(task, character_id=character_id)
    with pytest.raises(CharacterWorkError):
        await CodexCharacterWorkExecutor(tmp_path, None).prepare_workspace(task)
    with pytest.raises(CharacterWorkError):
        await artifacts.collect(task, directory, None, (), "done")
    assert not (tmp_path / "artifacts").exists()


@pytest.mark.anyio
@pytest.mark.parametrize("damage", ["change", "missing", "symlink", "bad_zip"])
async def test_damaged_saved_archive_is_never_returned(
    tmp_path: Path, damage: str
) -> None:
    task, directory, artifacts = _workspace(tmp_path)
    (directory / "memo.md").write_text("memo")
    snapshot = await artifacts.collect(task, directory, None, (), "done")
    path = tmp_path / "artifacts" / "100" / "101.zip"
    if damage == "change":
        path.write_bytes(path.read_bytes() + b"changed")
    elif damage == "missing":
        path.unlink()
    elif damage == "symlink":
        other = tmp_path / "copy.zip"
        path.rename(other)
        path.symlink_to(other)
    else:
        data = b"not a zip archive"
        path.write_bytes(data)
        snapshot = replace(
            snapshot, sha256=hashlib.sha256(data).hexdigest(), size=len(data)
        )
    with pytest.raises(CharacterWorkError):
        await artifacts.load(replace(task, artifacts=snapshot))
    assert await artifacts.load(task) == ()
