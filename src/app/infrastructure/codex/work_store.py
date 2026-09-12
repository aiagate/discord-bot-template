"""Atomic JSON storage for a single bot process's character tasks."""

import asyncio
import logging
import os
import tempfile
from pathlib import Path

from flow_res import Err, Result
from pydantic import TypeAdapter

from app.contracts.messages.character_work import CharacterWork, CharacterWorkError
from app.contracts.ports.character_work import (
    ICharacterWorkRequester,
    ICharacterWorkStore,
)

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

    async def recent_reviewed_work(
        self,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        limit: int = 3,
    ) -> list[CharacterWork]:
        """Read recent reviewed Discord work in one conversation scope."""
        if limit <= 0:
            return []
        tasks = await self.list_tasks()
        candidates = [
            task
            for task in tasks
            if task.origin == "discord"
            and task.status == "completed"
            and task.review.strip()
            and (task.guild_id, task.channel_id, task.owner_id)
            == (guild_id, channel_id, owner_id)
            and task.id.isascii()
            and task.id.isdecimal()
        ]
        candidates.sort(key=lambda task: int(task.id), reverse=True)
        return candidates[:limit]

    def _list(self) -> list[CharacterWork]:
        # ponytail: scan task files; use SQLite if retained tasks make lookup slow.
        return [
            _TASK.validate_json(path.read_bytes()) for path in self._root.glob("*.json")
        ]


class NullCharacterWorkStore(ICharacterWorkStore):
    """Keep normal Gemini responses available when Codex work is disabled."""

    async def save(self, task: CharacterWork) -> None:
        """Reject writes because character work is not configured."""
        raise CharacterWorkError("キャラクター作業が無効です。")

    async def list_tasks(self) -> list[CharacterWork]:
        """Return no records while character work is disabled."""
        return []

    async def recent_reviewed_work(
        self,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        limit: int = 3,
    ) -> list[CharacterWork]:
        """Return no reviewed work while character work is disabled."""
        return []


class NullCharacterWorkRequester(ICharacterWorkRequester):
    """Keep ordinary responses tool-free when Codex is not configured."""

    @property
    def enabled(self) -> bool:
        """Return false so the Gemini adapter does not advertise the tool."""
        return False

    def current(
        self, guild_id: str, channel_id: str, owner_id: str
    ) -> CharacterWork | None:
        """Return no linked work while the feature is disabled."""
        return None

    def can_submit(
        self,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        *,
        authorization_channel_id: str | None = None,
    ) -> bool:
        """Return false so the ordinary response never advertises work."""
        return False

    async def submit(
        self,
        *,
        guild_id: str,
        channel_id: str,
        owner_id: str,
        message_id: str,
        character_id: str,
        prompt: str,
        authorization_channel_id: str | None = None,
    ) -> Result[CharacterWork, CharacterWorkError]:
        """Reject tool requests because no executor is configured."""
        return Err(CharacterWorkError("キャラクター作業が無効です。"))
