"""Confirmed, sequential Discord Times board delivery with progress recovery."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from flow_res import Err, Ok, Result, is_err

from app.contracts.messages.times_message import TimesEpisodePlan
from app.contracts.ports.speech_publisher import (
    SpeechPublishError,
    SpeechPublishErrorType,
)
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.contracts.ports.times_publisher import ITimesPublisher
from app.domain.characters import CharacterRoster
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.discord.message_chunks import split_discord_content

logger = logging.getLogger(__name__)
SEND_TIMEOUT_SECONDS = 30.0
DELIVERY_TIMEOUT_SECONDS = 120.0


class DiscordWebhookTimesPublisher(ITimesPublisher):
    """Deliver Times posts sequentially and record each post before sending the next."""

    def __init__(
        self,
        webhook_url: str,
        *,
        client: discord.Client,
        store: ITimesEpisodeStore,
        roster: CharacterRoster,
    ) -> None:
        try:
            self._webhook = discord.Webhook.from_url(webhook_url, client=client)
        except ValueError:
            raise ValueError("Invalid Discord webhook URL.") from None
        self._client = client
        self._store = store
        self._roster = roster
        self._scope: DiscordConversationScope | None = None
        self._lock = asyncio.Lock()

    @property
    def webhook_id(self) -> int:
        """Return the identity used to distinguish our own webhook events."""
        return self._webhook.id

    @property
    def scope(self) -> DiscordConversationScope | None:
        """Return the validated conversation scope for the Times destination."""
        return self._scope

    async def initialize(
        self,
        guild_id: str,
        character_channel_ids: set[str] | frozenset[str] = frozenset(),
    ) -> DiscordConversationScope:
        """Resolve text destination; reject foreign guild, ForumChannel, or character channels."""
        async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
            webhook = await self._webhook.fetch(prefer_auth=False)
            if str(webhook.guild_id) != guild_id or webhook.channel_id is None:
                raise ValueError("Times webhook must belong to the configured guild.")
            channel = await self._client.fetch_channel(webhook.channel_id)
            if isinstance(channel, discord.ForumChannel):
                raise ValueError("Times webhook must not target a forum channel.")
            if not isinstance(channel, discord.TextChannel):
                raise ValueError("Times webhook must target a text channel.")
            if str(channel.guild.id) != guild_id:
                raise ValueError("Times channel belongs to a different guild.")
            if str(channel.id) in character_channel_ids:
                raise ValueError(
                    "Times webhook destination must not be a character response channel."
                )
            self._scope = DiscordConversationScope(
                guild_id=guild_id, channel_id=str(channel.id)
            )
            return self._scope

    async def _validate_destination(self) -> discord.TextChannel:
        """Revalidate the configured text channel before sending a post."""
        if self._scope is None:
            raise ValueError("Times webhook destination is not initialized.")
        webhook = await self._webhook.fetch(prefer_auth=False)
        if (
            str(webhook.guild_id) != self._scope.guild_id
            or str(webhook.channel_id) != self._scope.channel_id
        ):
            raise ValueError("The Times webhook was moved to another destination.")
        channel = await self._client.fetch_channel(int(self._scope.channel_id))
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("The Times destination is no longer a text channel.")
        if str(channel.guild.id) != self._scope.guild_id:
            raise ValueError("The Times channel belongs to another guild.")
        return channel

    async def _save(self, plan: TimesEpisodePlan) -> None:
        """Persist progress and fail closed when the progress cannot be saved."""
        result = await self._store.save(plan)
        if is_err(result):
            raise RuntimeError("Times delivery progress could not be saved.")

    async def _confirm_inflight_post(self, plan: TimesEpisodePlan) -> bool:
        """Check whether an interrupted post was accepted by Discord."""
        if plan.attempt_started_at is None or plan.next_post_index >= len(plan.posts):
            return False
        channel = await self._validate_destination()
        expected = split_discord_content(
            plan.posts[plan.next_post_index].content, limit=1850
        )
        remaining = list(expected)
        async for message in channel.history(
            after=plan.attempt_started_at - timedelta(seconds=1),
            before=plan.attempt_started_at
            + timedelta(seconds=SEND_TIMEOUT_SECONDS + 5),
            oldest_first=True,
            limit=None,
        ):
            if message.webhook_id != self.webhook_id:
                continue
            try:
                remaining.remove(message.content)
            except ValueError:
                continue
            if not remaining:
                return True
        return False

    async def _deliver_posts(self, plan: TimesEpisodePlan) -> None:
        if plan.failure is not None:
            raise RuntimeError(plan.failure)
        if self._scope is None or (
            plan.guild_id,
            plan.delivery_channel_id,
        ) != (self._scope.guild_id, self._scope.channel_id):
            raise ValueError("Times episode belongs to another destination.")
        if plan.status == "COMPLETED":
            return
        if plan.complete:
            await self._save(replace(plan, status="COMPLETED", attempt_started_at=None))
            return
        if not plan.posts:
            # Handle empty posts as a completed no-op
            updated = replace(
                plan,
                status="COMPLETED",
                next_post_index=0,
                attempt_started_at=None,
            )
            await self._save(updated)
            return

        current_plan = plan
        if current_plan.attempt_started_at is not None:
            if not await self._confirm_inflight_post(current_plan):
                failure = (
                    "Previous Times delivery could not be confirmed; "
                    "automatic resend was stopped."
                )
                failed_plan = replace(
                    current_plan,
                    failure=failure,
                    status="FAILED",
                    attempt_started_at=None,
                )
                await self._save(failed_plan)
                raise RuntimeError(failure)
            next_index = current_plan.next_post_index + 1
            current_plan = replace(
                current_plan,
                next_post_index=next_index,
                status=(
                    "COMPLETED"
                    if next_index >= len(current_plan.posts)
                    else "DELIVERING"
                ),
                attempt_started_at=None,
            )
            await self._save(current_plan)
            if current_plan.status == "COMPLETED":
                return

        for index in range(current_plan.next_post_index, len(current_plan.posts)):
            post = current_plan.posts[index]
            character = next(
                (
                    c
                    for c in self._roster.characters
                    if c.name.casefold() == post.character_name.casefold()
                ),
                None,
            )
            if character is None:
                failure = f"Character '{post.character_name}' not found in roster."
                failed_plan = replace(current_plan, failure=failure, status="FAILED")
                await self._save(failed_plan)
                raise ValueError(failure)

            chunks = split_discord_content(post.content, limit=1850)
            current_plan = replace(
                current_plan,
                attempt_started_at=datetime.now(UTC),
            )
            await self._save(current_plan)
            try:
                for chunk in chunks:
                    async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                        await self._validate_destination()
                        send_kwargs: dict[str, Any] = {
                            "content": chunk,
                            "username": character.name,
                            "avatar_url": character.avatar_url,
                            "allowed_mentions": discord.AllowedMentions.none(),
                            "wait": True,
                        }
                        sent = await self._webhook.send(**send_kwargs)
                        if sent is None:
                            raise RuntimeError(
                                "Discord did not return the Times message."
                            )
            except discord.HTTPException as error:
                if 400 <= error.status < 500 and error.status != 429:
                    failed_plan = replace(
                        current_plan,
                        failure=f"Discord rejected delivery (HTTP {error.status}).",
                        status="FAILED",
                    )
                    await self._save(failed_plan)
                raise

            # Save successful delivery progress before sending the next post
            next_index = index + 1
            is_complete = next_index >= len(plan.posts)
            current_plan = replace(
                current_plan,
                next_post_index=next_index,
                status="COMPLETED" if is_complete else "DELIVERING",
                attempt_started_at=None,
            )
            await self._save(current_plan)

    async def deliver(self, plan: TimesEpisodePlan) -> Result[None, SpeechPublishError]:
        """Deliver whole episode serially and persist every acknowledged post."""
        try:
            async with asyncio.timeout(DELIVERY_TIMEOUT_SECONDS), self._lock:
                await self._deliver_posts(plan)
            return Ok(None)
        except Exception as error:
            logger.error("Times delivery failed (%s): %s", type(error).__name__, error)
            return Err(
                SpeechPublishError(
                    type=SpeechPublishErrorType.INVALID_PAYLOAD
                    if isinstance(error, ValueError)
                    else SpeechPublishErrorType.DELIVERY_FAILED,
                    message="Times delivery failed; progress is retained for recovery.",
                )
            )

    async def recover_pending(self) -> None:
        """Recover pending deliveries that have already been generated."""
        async with asyncio.timeout(DELIVERY_TIMEOUT_SECONDS), self._lock:
            pending = await self._store.pending()
            if is_err(pending):
                raise RuntimeError("Pending Times delivery progress could not be read.")
            for plan in pending.value:
                if plan.failure is None and plan.posts:
                    try:
                        await self._deliver_posts(plan)
                    except Exception:
                        latest = await self._store.get(plan.source_message_id)
                        if (
                            is_err(latest)
                            or latest.value is None
                            or latest.value.failure is None
                        ):
                            raise
                        logger.error(
                            "Stopped unconfirmed Times delivery for source %s: %s",
                            plan.source_message_id,
                            latest.value.failure,
                        )
