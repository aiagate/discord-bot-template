"""Atomic JSON storage for a single bot process's character tasks."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from pydantic import TypeAdapter

from app.contracts.messages.character_work import CharacterWork, CharacterWorkError
from app.contracts.ports.character_work import ICharacterWorkStore

logger = logging.getLogger(__name__)
_TASK = TypeAdapter(CharacterWork)


class FileCharacterWorkStore(ICharacterWorkStore):
    """Keep work state durable without placing it in an agent workspace."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve()

    async def save(self, task: CharacterWork) -> None:
        """Replace one task document atomically."""
        if not task.id.isascii() or not task.id.isdecimal():
            raise CharacterWorkError("作業IDが不正です。")
        try:
            writing = asyncio.create_task(asyncio.to_thread(self._save, task))
            try:
                await asyncio.shield(writing)
            except asyncio.CancelledError:
                await writing
                raise
        except (OSError, ValueError) as error:
            logger.exception("Could not save character work")
            raise CharacterWorkError("作業の保存に失敗しました。") from error

    def _save(self, task: CharacterWork) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = self._root / f"{task.id}.json"
        descriptor, name = tempfile.mkstemp(dir=self._root, suffix=".tmp")
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(_TASK.dump_json(task))
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(name, target)
        finally:
            Path(name).unlink(missing_ok=True)

    async def list_tasks(self) -> list[CharacterWork]:
        """Read tasks, rejecting corrupt state instead of rerunning work."""
        try:
            return await asyncio.to_thread(self._list)
        except (OSError, ValueError) as error:
            logger.exception("Could not read character work")
            raise CharacterWorkError("作業記録を読み込めませんでした。") from error

    def _list(self) -> list[CharacterWork]:
        # ponytail: scan task files; use SQLite if retained tasks make lookup slow.
        return [
            _TASK.validate_json(path.read_bytes()) for path in self._root.glob("*.json")
        ]
