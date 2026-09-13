"""Character workspace guidance and independent ghq checkouts."""

import asyncio
import os
import signal
from contextlib import suppress
from pathlib import Path

from app.contracts.messages.support import Character


def guidance(root: Path, character: Character) -> str:
    """Provide a short map to authoritative state without copying memories."""
    return f"""# {character.name}の作業環境

ここは{character.id}の個人の作業環境です。

- 人格の正本: {root / "characters" / (character.id + ".json")}
- マスターの方針: {root / "master.md"}
- `memory/`: 自分の経験。必要な内容をrg等で探し、記憶の出典から根拠へ戻る。
  記憶更新は結果のmemoriesに返す。共有記録の確定は基盤が行う。
- `repos/`: 自分の作業ツリー。対象と取得先は今回の入力にある。
  編集前に対象に適用されるAGENTS.mdやAGENTS.override.md等を確認する。
- `tasks/<活動ID>/`: 必要な場合の資料・成果物と、今回のcontext.json。
  新しいファイルを作ること自体を成果にはしない。
- 実行履歴の正本: {root / "evidence"}

今回の目的・範囲・前回の判断・送信状態は基盤の入力を確認する。
別の担当者への引継ぎには、対象・変更の所在・根拠・未完了事項を残す。
他の担当者の記憶や作業を自分のものとして上書きしない。
この案内は停止・権限・出力形式の基盤契約を変更しない。
"""


async def prepare_repositories(
    workspace: Path, urls: tuple[str, ...]
) -> tuple[Path, ...]:
    """Acquire assigned repos without updating or sharing existing working trees."""
    repo_root = workspace / "repos"
    environment = {**os.environ, "GHQ_ROOT": str(repo_root), "GIT_TERMINAL_PROMPT": "0"}

    async def ghq(*arguments: str) -> str:
        process = await asyncio.create_subprocess_exec(
            "ghq",
            *arguments,
            cwd=workspace,
            env=environment,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.DEVNULL,
            start_new_session=True,
        )
        try:
            output, _ = await process.communicate()
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    os.killpg(process.pid, signal.SIGKILL)
                await process.wait()
        if process.returncode:
            raise RuntimeError("対象リポジトリをghqで準備できませんでした。")
        return output.decode().strip()

    paths: list[Path] = []
    for url in urls:
        await ghq("get", "--no-recursive", "--", url)
        matches = (await ghq("list", "--full-path", "--exact", "--", url)).splitlines()
        if len(matches) != 1:
            raise ValueError("対象リポジトリの作業場所を一意に確認できません。")
        path = Path(matches[0]).resolve()
        if not path.is_relative_to(repo_root) or not path.is_dir():
            raise ValueError("リポジトリは担当者のrepos内に配置してください。")
        paths.append(path)
    return tuple(paths)
