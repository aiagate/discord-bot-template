"""Build bounded application context for Codex character work."""

from __future__ import annotations

import json
from datetime import datetime
from typing import cast

from flow_res import is_err

from app.contracts.messages.character_prompt import (
    MAX_MASTER_CONTEXT_LENGTH,
    UNCONFIGURED_MASTER,
    DiscordMaster,
    prompt_datetime,
)
from app.contracts.messages.character_work import CharacterWork
from app.contracts.messages.user_memory import UserMemoryContext
from app.contracts.ports.character_memory_store import ICharacterMemoryStore
from app.contracts.ports.character_work import (
    ICharacterWorkContextProvider,
    ICharacterWorkStore,
)
from app.contracts.ports.chat_history_query import IChatHistoryQuery
from app.contracts.ports.user_memory import IUserMemoryStore
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.character_memory import CharacterMemory
from app.domain.value_objects import ChatPlatform, DiscordConversationScope

MAX_HISTORY_MESSAGES = 8
MAX_HISTORY_MESSAGE_LENGTH = 1000
MAX_CHARACTER_MEMORIES = 8
MAX_MEMORY_LENGTH = 500
MAX_COMPLETED_WORK = 3
MAX_REVIEW_LENGTH = 1600
MAX_CONTEXT_LENGTH = 16000


def _clip(value: str, limit: int) -> str:
    """Trim one untrusted value while keeping the context bounded."""
    return value.strip()[:limit]


def _message_text(message: ChatMessage) -> str:
    """Read text content without assuming a provider-specific payload shape."""
    value = message.content.payload.get("text", "")
    return value if isinstance(value, str) else str(value)


class CharacterWorkContextProvider(ICharacterWorkContextProvider):
    """Read scoped conversation and memory context for direct Discord work."""

    def __init__(
        self,
        history_query: IChatHistoryQuery,
        character_memory_store: ICharacterMemoryStore,
        user_memory_store: IUserMemoryStore,
        work_store: ICharacterWorkStore,
        master: DiscordMaster = UNCONFIGURED_MASTER,
    ) -> None:
        self._history_query = history_query
        self._character_memory_store = character_memory_store
        self._user_memory_store = user_memory_store
        self._work_store = work_store
        self._master = master

    async def build(self, task: CharacterWork) -> str:
        """Return a bounded JSON reference context for one direct task."""
        if task.origin != "discord":
            return ""

        scope = DiscordConversationScope(
            guild_id=task.guild_id,
            channel_id=task.channel_id,
        )
        source = await self._source(task, scope)
        cursor = (
            (source.occurred_at, source.id.to_primitive())
            if source is not None
            else None
        )
        history = await self._history(scope, cursor)
        character_memory = await self._character_memory(task, cursor)
        user_memory = await self._user_memory(source)
        completed_work = await self._completed_work(task)
        master = self._master.to_prompt()
        if master is not None and "context" in master:
            master = {
                **master,
                "context": _clip(master["context"], MAX_MASTER_CONTEXT_LENGTH),
            }

        payload: dict[str, object] = {
            "scope": {
                "guild_id": task.guild_id,
                "channel_id": task.channel_id,
                "owner_id": task.owner_id,
            },
            "master": master,
            "conversation_history": [
                {
                    "message_id": message.external_message_id,
                    "author_name": message.author_name,
                    "author_kind": message.author_kind.to_primitive(),
                    "occurred_at": prompt_datetime(message.occurred_at),
                    "content": _clip(
                        _message_text(message), MAX_HISTORY_MESSAGE_LENGTH
                    ),
                }
                for message in history
                if _message_text(message).strip()
            ],
            "character_memory": [
                {
                    "source_message_id": memory.source_message_id,
                    "observed_at": prompt_datetime(memory.observed_at),
                    "content": _clip(memory.content, MAX_MEMORY_LENGTH),
                }
                for memory in character_memory
            ],
            "user_memory": self._user_memory_payload(user_memory),
            "completed_work": [
                {
                    "work_id": work.id,
                    "character_id": work.character_id,
                    "summary": _clip(work.review, MAX_REVIEW_LENGTH),
                }
                for work in completed_work
            ],
        }
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= MAX_CONTEXT_LENGTH:
            return encoded
        reduced = {
            "scope": payload["scope"],
            "master": payload["master"],
            "conversation_history": cast(
                list[dict[str, object]], payload["conversation_history"]
            )[-4:],
            "character_memory": cast(
                list[dict[str, object]], payload["character_memory"]
            )[:4],
            "user_memory": payload["user_memory"],
            "completed_work": cast(list[dict[str, object]], payload["completed_work"])[
                :1
            ],
            "truncated": True,
        }
        encoded = json.dumps(reduced, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= MAX_CONTEXT_LENGTH:
            return encoded
        return json.dumps(
            {"scope": payload["scope"], "truncated": True},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    async def _source(
        self,
        task: CharacterWork,
        scope: DiscordConversationScope,
    ) -> ChatMessage | None:
        """Read the persisted request without crossing the conversation scope."""
        try:
            result = await self._history_query.get_by_external_id(
                ChatPlatform.DISCORD,
                task.last_message_id,
            )
        except Exception:
            return None
        if is_err(result) or result.value is None:
            return None
        source = result.value
        if source.conversation_scope != scope:
            return None
        if source.external_sender_id.to_primitive() != task.owner_id:
            return None
        return source

    async def _history(
        self,
        scope: DiscordConversationScope,
        cursor: tuple[datetime, str] | None,
    ) -> list[ChatMessage]:
        """Read only recent history before the current work request."""
        if cursor is None:
            return []
        try:
            result = await self._history_query.get_recent_history(
                scope,
                limit=MAX_HISTORY_MESSAGES,
                before=cursor,
            )
        except Exception:
            return []
        return [] if is_err(result) else result.value

    async def _character_memory(
        self,
        task: CharacterWork,
        cursor: tuple[datetime, str] | None,
    ) -> list[CharacterMemory]:
        """Read memories owned by the assigned character."""
        try:
            result = await self._character_memory_store.get_relevant(
                character_id=task.character_id,
                limit=MAX_CHARACTER_MEMORIES,
                before=cursor,
            )
        except Exception:
            return []
        return [] if is_err(result) else result.value

    async def _user_memory(
        self, source: ChatMessage | None
    ) -> UserMemoryContext | None:
        """Resolve the owner and read only that user's private memory."""
        if source is None or source.user_id is None:
            return None
        try:
            result = await self._user_memory_store.get_context(
                source.user_id.to_primitive(),
                limit=8,
            )
        except Exception:
            return None
        return None if is_err(result) else result.value

    async def _completed_work(self, task: CharacterWork) -> list[CharacterWork]:
        """Read reviewed direct work from the same owner and conversation only."""
        try:
            return await self._work_store.recent_reviewed_work(
                task.guild_id,
                task.channel_id,
                task.owner_id,
                limit=MAX_COMPLETED_WORK,
            )
        except Exception:
            return []

    @staticmethod
    def _user_memory_payload(
        memory: UserMemoryContext | None,
    ) -> dict[str, object] | None:
        """Serialize a bounded private memory view without exposing source IDs."""
        if memory is None:
            return None
        profile = memory.profile
        return {
            "profile": (
                {
                    "summary": _clip(profile.summary, 1000),
                    "traits": [_clip(item, 200) for item in profile.traits[:10]],
                    "preferences": [
                        _clip(item, 200) for item in profile.preferences[:10]
                    ],
                }
                if profile is not None
                else None
            ),
            "timeline": [
                {
                    "day": entry.day,
                    "title": _clip(entry.title, 160),
                    "summary": _clip(entry.summary, 1000),
                    "occurred_at": prompt_datetime(entry.occurred_at),
                }
                for entry in memory.timeline[:8]
            ],
        }
