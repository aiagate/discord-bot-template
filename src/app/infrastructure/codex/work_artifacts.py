"""Collect bounded, verified file snapshots outside writable workspaces."""

import ast
import asyncio
import hashlib
import io
import json
import os
import re
import stat
import tempfile
import tomllib
import zipfile
from dataclasses import asdict
from pathlib import Path, PurePosixPath

from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkArtifacts,
    WorkAttachment,
    WorkCommandEvidence,
)

MAX_FILES = 100
MAX_CANDIDATES = 1000
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_TOTAL_BYTES = 6 * 1024 * 1024
MAX_ARCHIVE_BYTES = 8 * 1024 * 1024
_PRIVATE = {
    ".git",
    ".codex",
    ".agents",
    ".ssh",
    ".aws",
    "auth.json",
    "credentials.json",
}
_CACHES = {
    ".tmp",
    ".venv",
    "venv",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
}


def _identifier(value: str) -> str:
    if not value.isascii() or not value.isdecimal() or len(value) > 20:
        raise CharacterWorkError("成果物のIDが不正です。")
    return value


def _relative(path: str) -> tuple[str, ...]:
    parts = tuple(path.split("/"))
    if (
        not path
        or len(path) > 1000
        or "\\" in path
        or any(ord(character) < 32 for character in path)
        or any(part in {"", ".", ".."} for part in parts)
    ):
        raise CharacterWorkError("作業場所内の相対パスではありません。")
    return parts


def _excluded(path: str) -> bool:
    return any(
        part.casefold() in _PRIVATE | _CACHES
        or part.casefold().startswith((".env", "id_rsa", "id_ed25519"))
        or part.casefold().endswith((".pem", ".key", ".p12", ".pfx"))
        for part in _relative(path)
    )


def _read(root: Path, path: str, limit: int) -> bytes:
    parts = _relative(path)
    descriptor = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        for part in parts[:-1]:
            child = os.open(
                part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=descriptor
            )
            os.close(descriptor)
            descriptor = child
        file_descriptor = os.open(
            parts[-1],
            os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK,
            dir_fd=descriptor,
        )
        with os.fdopen(file_descriptor, "rb") as stream:
            before = os.fstat(stream.fileno())
            if not stat.S_ISREG(before.st_mode) or before.st_nlink != 1:
                raise CharacterWorkError("通常ファイルではないか、ハードリンクです。")
            if before.st_size > limit:
                raise CharacterWorkError("添付サイズの上限を超えています。")
            data = stream.read(limit + 1)
            after = os.fstat(stream.fileno())
            if len(data) != before.st_size or (
                before.st_size,
                before.st_mtime_ns,
                before.st_ctime_ns,
            ) != (after.st_size, after.st_mtime_ns, after.st_ctime_ns):
                raise CharacterWorkError("収集中にファイルが変更されました。")
            return data
    finally:
        os.close(descriptor)


def _syntax(path: str, data: bytes) -> str:
    suffix = PurePosixPath(path).suffix.casefold()
    if suffix not in {".py", ".json", ".toml"}:
        return "not_checked"
    try:
        if suffix == ".py":
            ast.parse(data, filename=path)
        elif suffix == ".json":
            json.loads(data)
        else:
            tomllib.loads(data.decode("utf-8"))
    except (ValueError, SyntaxError, RecursionError):
        return "failed"
    return "passed"


def _workspace_files(directory: Path) -> list[tuple[str, str]]:
    paths: list[tuple[str, str]] = []
    visited = 0

    def unreadable(error: OSError) -> None:
        raise error

    for parent, directories, files in os.walk(
        directory, followlinks=False, onerror=unreadable
    ):
        visited += len(directories) + len(files)
        if visited > MAX_CANDIDATES:
            raise CharacterWorkError("成果候補が多すぎます。作業を分割してください。")
        descend: list[str] = []
        for name in sorted(directories):
            entry = Path(parent) / name
            path = entry.relative_to(directory).as_posix()
            if _excluded(path) or entry.is_symlink():
                paths.append((path, "file"))
            else:
                descend.append(name)
        directories[:] = descend
        for name in sorted(files):
            paths.append(
                ((Path(parent) / name).relative_to(directory).as_posix(), "file")
            )
    return paths


class FileWorkArtifacts:
    """Save actual file bytes, syntax checks, and command evidence in one archive."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def collect(
        self,
        task: CharacterWork,
        directory: Path,
        changes: list[tuple[str, str]] | None,
        commands: tuple[WorkCommandEvidence, ...],
        report: str,
    ) -> WorkArtifacts:
        """Snapshot eligible files; represent rejected files explicitly in the manifest."""
        expected = self._root / "workspaces" / task.character_id / _identifier(task.id)
        if (
            re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", task.character_id) is None
            or directory.resolve() != expected
        ):
            raise CharacterWorkError("成果物の作業場所が不正です。")
        try:
            return await asyncio.to_thread(
                self._collect, task, directory, changes, commands, report
            )
        except OSError as error:
            raise CharacterWorkError("成果物を保存できませんでした。") from error

    def _collect(
        self,
        task: CharacterWork,
        directory: Path,
        changes: list[tuple[str, str]] | None,
        commands: tuple[WorkCommandEvidence, ...],
        report: str,
    ) -> WorkArtifacts:
        candidates = _workspace_files(directory) if changes is None else changes
        if len(candidates) > MAX_CANDIDATES:
            raise CharacterWorkError("成果候補が多すぎます。作業を分割してください。")
        records: list[dict[str, str | int]] = []
        contents: dict[str, bytes] = {}
        total = 0
        for path, change in sorted(set(candidates)):
            record: dict[str, str | int] = {"path": path, "change": change}
            records.append(record)
            try:
                if _excluded(path):
                    raise CharacterWorkError(
                        "秘密情報・管理情報・キャッシュは添付しません。"
                    )
                if change == "deleted":
                    record["status"] = "deleted"
                    continue
                if len(contents) >= MAX_FILES:
                    raise CharacterWorkError("添付ファイル数の上限を超えています。")
                data = _read(
                    directory, path, min(MAX_FILE_BYTES, MAX_TOTAL_BYTES - total)
                )
                contents[path] = data
                total += len(data)
                record.update(
                    status="included",
                    size=len(data),
                    sha256=hashlib.sha256(data).hexdigest(),
                    syntax=_syntax(path, data),
                )
            except (OSError, CharacterWorkError) as error:
                record.update(
                    status="excluded",
                    reason=str(error)
                    if isinstance(error, CharacterWorkError)
                    else "リンク・特殊ファイル・読み取りエラーです。",
                )

        syntax_passed = sum(item.get("syntax") == "passed" for item in records)
        syntax_failed = sum(item.get("syntax") == "failed" for item in records)
        excluded = sum(item["status"] == "excluded" for item in records)
        deleted = sum(item["status"] == "deleted" for item in records)
        failed_commands = sum(
            item.exit_code is not None and item.exit_code != 0 for item in commands
        )
        pending_commands = sum(item.exit_code is None for item in commands)
        summary = (
            f"成果: {len(contents)}ファイル、削除{deleted}件、添付除外{excluded}件。\n"
            f"構文検査（Python/JSON/TOML）: 成功{syntax_passed}件・失敗{syntax_failed}件。\n"
            f"コマンド記録: {len(commands)}件（非0終了{failed_commands}件・未確定{pending_commands}件）。\n"
            "ZIPと各ファイルのSHA-256を照合しました。検査の詳細と実行出力はmanifest.jsonに記録しています。"
        )
        manifest = {
            "version": 1,
            "task_id": task.id,
            "revision_id": task.last_message_id,
            "files": records,
            "commands": [asdict(item) for item in commands],
            "summary": summary,
        }
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("report.md", report[:32000])
            archive.writestr(
                "manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2)
            )
            for path, data in contents.items():
                archive.writestr(f"files/{path}", data)
        data = buffer.getvalue()
        if len(data) > MAX_ARCHIVE_BYTES:
            raise CharacterWorkError("成果ZIPが添付サイズの上限を超えています。")
        self._verify(data)
        revision = _identifier(task.last_message_id)
        target = self._root / "artifacts" / task.id / f"{revision}.zip"
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.link(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return WorkArtifacts(
            revision,
            hashlib.sha256(data).hexdigest(),
            len(data),
            len(contents),
            summary,
        )

    @staticmethod
    def _verify(data: bytes) -> None:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            if archive.testzip() is not None:
                raise CharacterWorkError("成果ZIPの検証に失敗しました。")
            manifest = json.loads(archive.read("manifest.json"))
            for record in manifest["files"]:
                if record["status"] == "included":
                    content = archive.read("files/" + record["path"])
                    if (
                        len(content) != record["size"]
                        or hashlib.sha256(content).hexdigest() != record["sha256"]
                    ):
                        raise CharacterWorkError(
                            "成果ファイルのハッシュが一致しません。"
                        )

    async def load(self, task: CharacterWork) -> tuple[WorkAttachment, ...]:
        """Return the saved bytes after checking archive and member integrity."""
        if task.artifacts is None:
            return ()
        artifacts = task.artifacts
        path = f"{_identifier(task.id)}/{_identifier(artifacts.revision_id)}.zip"
        try:
            data = await asyncio.to_thread(
                _read, self._root / "artifacts", path, MAX_ARCHIVE_BYTES
            )
            if (
                len(data) != artifacts.size
                or hashlib.sha256(data).hexdigest() != artifacts.sha256
            ):
                raise CharacterWorkError("保存済み成果のハッシュが一致しません。")
            await asyncio.to_thread(self._verify, data)
        except (OSError, ValueError, KeyError, zipfile.BadZipFile) as error:
            raise CharacterWorkError("保存済み成果を読み取れませんでした。") from error
        return (
            WorkAttachment(
                f"{task.character_id}-{task.id}-{artifacts.revision_id}.zip", data
            ),
        )
