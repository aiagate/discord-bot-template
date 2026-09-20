"""Stable personal workspaces and recoverable Markdown projections."""

import hashlib
import json
import os
from pathlib import Path

from app.contracts.messages.collective import CollectiveState, WorkContext


def atomic_write(path: Path, content: str) -> None:
    """Replace a file only after its complete content has reached disk."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("w") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def run_directory(context: WorkContext) -> Path:
    """Map an opaque run key to a stable, filesystem-safe path."""
    return (
        context.workspace
        / "runs"
        / hashlib.sha256(f"{context.run_id}:{context.attempt}".encode()).hexdigest()[
            :24
        ]
    )


class CharacterWorkspaces:
    """Project only the selected person's snapshot before a serial work run."""

    def __init__(self, root: Path, skill_path: Path, guide_bytes: int = 32768) -> None:
        self.root = root.resolve()
        self.skill_path = skill_path.resolve()
        self.guide_bytes = guide_bytes

    def _guide(self, workspace: Path) -> str:
        return f"""# 本人の作業場所

- 人格: `character.json`
- マスターの方針: `master/policy.md`
- マスターの記憶: `master/`、本人の記憶: `memory/`
- 出典: `sources.json`、投影版: `projection.json`
- 資料と成果: `tasks/`、実行記録: `runs/`
- リポジトリ: `repos/`。GHQ_ROOTはこの場所。取得はghq getを使う。
- AGY: `{self.skill_path}` を読み、文章作成・添削にCLIを利用して結果を確認する。
- 現在の資料一覧: `workspace-index.md`

編集前に対象リポジトリのAGENTS.mdを読む。記憶更新は結果のmemoriesへ返す。
この案内の更新は`guide-notes.md`で提案する。詳細は参照先へ置き、短く保つ。
停止・訂正と今回の入力を優先し、前回が結果不明なら実状態を確認してから再開する。
"""

    def _guidance(self, workspace: Path) -> None:
        paths: list[Path] = []
        home = Path(os.environ.get("CODEX_HOME", str(Path.home() / ".codex")))
        candidates = [home, *reversed(workspace.parents), workspace]
        for directory in candidates:
            selected = next(
                (
                    directory / name
                    for name in ("AGENTS.override.md", "AGENTS.md")
                    if (directory / name).is_file()
                ),
                None,
            )
            if (
                selected is not None
                and selected not in paths
                and selected.parent != workspace
            ):
                paths.append(selected)
        guide = self._guide(workspace)
        notes = workspace / "guide-notes.md"
        if notes.exists():
            guide += "\n追加の案内: `guide-notes.md`\n"
        history = workspace / "guide-history"
        if history.exists():
            guide += "\n以前の案内: `guide-history/`\n"
        existing = workspace / "AGENTS.md"
        if existing.exists() and existing.read_text() != guide:
            previous = existing.read_text()
            atomic_write(
                history / f"{hashlib.sha256(previous.encode()).hexdigest()[:16]}.md",
                previous,
            )
            if "`guide-history/`" not in guide:
                guide += "\n以前の案内: `guide-history/`\n"
        if (workspace / "AGENTS.override.md").exists():
            raise ValueError(
                "Personal AGENTS.override.md hides required workspace references"
            )
        total = len(guide.encode()) + sum(path.stat().st_size for path in paths)
        if total > self.guide_bytes:
            raise ValueError(
                f"Combined instruction files exceed {self.guide_bytes} bytes ({total})"
            )
        atomic_write(existing, guide)
        files = sorted(
            str(path.relative_to(workspace))
            for path in (workspace / "tasks").rglob("*")
            if path.is_file()
        )
        atomic_write(
            workspace / "workspace-index.md",
            "\n".join(f"- `{path}`" for path in files) + "\n",
        )

    def prepare(self, context: WorkContext, state: CollectiveState) -> WorkContext:
        """Refresh the same workspace, checking every projected file before launch."""
        if not self.skill_path.is_file():
            raise ValueError("Configured AGY skill is missing")
        workspace = (self.root / "work" / context.context.character.id).resolve()
        if context.workspace.resolve() != workspace:
            raise ValueError("Unexpected character workspace")
        workspace.mkdir(parents=True, exist_ok=True)
        for directory in ("memory", "master", "repos", "tasks", "runs"):
            (workspace / directory).mkdir(exist_ok=True)
        atomic_write(
            workspace / "character.json",
            context.context.character.model_dump_json(indent=2),
        )
        atomic_write(workspace / "master" / "policy.md", context.context.master)
        desired: dict[Path, str] = {}
        sources: set[str] = set()
        for key, version in context.context.memory_versions.items():
            memory = state.memories[key]
            if memory.version != version:
                raise ValueError(
                    "Memory changed before projection; rebuild the work input"
                )
            if memory.deleted:
                continue
            directory = "master" if memory.owner == "master" else "memory"
            path = workspace / directory / f"{memory.section}-{memory.note_id}.md"
            desired[path] = (
                f"{memory.content}\n\n出典: {', '.join(memory.sources)}\n版: {memory.version}\n"
            )
            sources.update(memory.sources)
        for directory in ("master", "memory"):
            for path in (workspace / directory).glob("*.md"):
                if path.name != "policy.md" and path not in desired:
                    path.unlink()
        for path, content in desired.items():
            atomic_write(path, content)
        atomic_write(
            workspace / "sources.json",
            json.dumps(
                {
                    source: state.events[source].model_dump(mode="json")
                    for source in sources
                },
                ensure_ascii=False,
                indent=2,
            ),
        )
        if any(path.read_text() != content for path, content in desired.items()):
            raise OSError("Memory projection verification failed")
        atomic_write(
            workspace / "projection.json", json.dumps(context.context.memory_versions)
        )
        self._guidance(workspace)
        run = run_directory(context)
        run.mkdir(parents=True, exist_ok=True)
        references = {
            "personality": str(workspace / "character.json"),
            "master": str(workspace / "master"),
            "memory": str(workspace / "memory"),
            "sources": str(workspace / "sources.json"),
            "agy_skill": str(self.skill_path),
            "run": str(run),
        }
        if context.activity:
            task = workspace / "tasks" / context.activity.id
            task.mkdir(exist_ok=True)
            references["task"] = str(task)
        result = context.model_copy(
            update={"workspace": workspace, "references": references}
        )
        atomic_write(run / "input.json", result.model_dump_json(indent=2))
        return result
