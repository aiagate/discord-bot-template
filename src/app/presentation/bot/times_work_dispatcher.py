"""Connect completed Times discussions with character work and follow-ups."""

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import UTC, datetime

from flow_res import is_err

from app.contracts.messages.character_work import CharacterWork
from app.contracts.messages.times_message import (
    TimesEpisodePlan,
    TimesPost,
    TimesWorkIntent,
)
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.contracts.ports.times_publisher import ITimesPublisher
from app.domain.characters import CharacterRoster
from app.domain.value_objects import DiscordConversationScope

logger = logging.getLogger(__name__)
TimesWorkStarter = Callable[
    [TimesEpisodePlan, TimesWorkIntent], Awaitable[CharacterWork | None]
]


class TimesWorkDispatcher:
    """Start committed Times work and publish its reviewed result back to Times."""

    def __init__(
        self,
        store: ITimesEpisodeStore,
        publisher: ITimesPublisher,
        roster: CharacterRoster,
        delivery_channel_id: str,
        starter: TimesWorkStarter,
    ) -> None:
        self._store = store
        self._publisher = publisher
        self._characters = {
            character.character_id: character for character in roster.characters
        }
        self._delivery_channel_id = delivery_channel_id
        self._starter = starter
        self._retry_lock = asyncio.Lock()

    async def dispatch(self, plan: TimesEpisodePlan) -> None:
        """Start each persisted work intent after its Times posts are delivered."""
        if not plan.complete or not plan.work_intents:
            return
        updated = list(plan.work_intents)
        changed = False
        for index, intent in enumerate(plan.work_intents):
            if intent.work_id is not None:
                continue
            task = await self._starter(plan, intent)
            if task is None:
                continue
            updated[index] = replace(intent, work_id=task.id)
            changed = True
        if not changed:
            return
        saved = await self._store.save(replace(plan, work_intents=tuple(updated)))
        if is_err(saved):
            logger.error(
                "Could not persist Times work links for episode %s: %s",
                plan.source_message_id,
                saved.error.message,
            )

    async def retry_pending(self, task: CharacterWork) -> None:
        """Retry unlinked intents from every completed episode after a slot frees."""
        async with self._retry_lock:
            completed = await self._store.get_completed_with_work(
                DiscordConversationScope(
                    guild_id=task.guild_id,
                    channel_id=self._delivery_channel_id,
                )
            )
            if is_err(completed):
                logger.error(
                    "Could not read pending Times work intents: %s",
                    completed.error.message,
                )
                return
            for plan in completed.value:
                await self.dispatch(plan)

    async def publish_completion(self, task: CharacterWork) -> None:
        """Publish one reviewed work result as a natural Times follow-up."""
        if not task.review:
            logger.warning("Skipping unreviewed Times work %s", task.id)
            return
        character = self._characters.get(task.character_id)
        if character is None:
            logger.error("Skipping Times work %s with unknown character", task.id)
            return
        source_message_id = f"work:{task.id}"
        existing = await self._store.get(source_message_id)
        if is_err(existing):
            logger.error(
                "Could not read Times follow-up %s: %s",
                source_message_id,
                existing.error.message,
            )
            return
        if existing.value is not None:
            if existing.value.status == "COMPLETED" or existing.value.complete:
                return
            retry_plan = existing.value
            if retry_plan.failure is not None:
                retry_plan = replace(
                    retry_plan,
                    failure=None,
                    status="PENDING",
                    attempt_started_at=None,
                )
                saved_retry = await self._store.save(retry_plan)
                if is_err(saved_retry):
                    logger.error(
                        "Could not reopen Times follow-up %s: %s",
                        source_message_id,
                        saved_retry.error.message,
                    )
                    return
            if retry_plan.posts:
                delivered = await self._publisher.deliver(retry_plan)
                if is_err(delivered):
                    logger.error(
                        "Could not resume Times follow-up %s: %s",
                        source_message_id,
                        delivered.error.message,
                    )
                return
            return

        plan = TimesEpisodePlan(
            source_message_id=source_message_id,
            guild_id=task.guild_id,
            channel_id=task.origin_channel_id or task.channel_id,
            delivery_channel_id=self._delivery_channel_id,
            posts=(TimesPost(character_name=character.name, content=task.review),),
            status="PENDING",
            next_post_index=0,
            owner_id=task.owner_id,
            created_at=datetime.now(UTC),
        )
        saved = await self._store.save(plan)
        if is_err(saved):
            logger.error(
                "Could not save Times follow-up %s: %s",
                source_message_id,
                saved.error.message,
            )
            return
        delivered = await self._publisher.deliver(plan)
        if is_err(delivered):
            logger.error(
                "Could not deliver Times follow-up %s: %s",
                source_message_id,
                delivered.error.message,
            )
