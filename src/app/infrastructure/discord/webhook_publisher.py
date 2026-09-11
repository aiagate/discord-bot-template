"""Confirmed, ordered Discord delivery with durable recovery of partial responses."""

import asyncio
import logging
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Any

import discord
from flow_res import Err, Ok, Result, is_err

from app.contracts.messages.character_prompt import UNCONFIGURED_MASTER, DiscordMaster
from app.contracts.messages.speech_message import (
    CharacterSpeechMessage,
    PublishedSpeech,
    SpeechDeliveryPlan,
)
from app.contracts.ports.speech_delivery_store import ISpeechDeliveryStore
from app.contracts.ports.speech_publisher import (
    ISpeechPublisher,
    SpeechPublishError,
    SpeechPublishErrorType,
)
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.discord.message_chunks import split_discord_content

logger = logging.getLogger(__name__)
SEND_TIMEOUT_SECONDS = 30.0
DELIVERY_TIMEOUT_SECONDS = 120.0
STORE_TIMEOUT_SECONDS = 5.0


class DiscordWebhookSpeechPublisher(ISpeechPublisher):
    """Deliver whole responses serially and persist every acknowledged part."""

    def __init__(
        self,
        webhook_url: str,
        *,
        client: discord.Client,
        store: ISpeechDeliveryStore,
        master: DiscordMaster = UNCONFIGURED_MASTER,
    ) -> None:
        try:
            self._webhook = discord.Webhook.from_url(webhook_url, client=client)
        except ValueError:
            raise ValueError("Invalid Discord webhook URL.") from None
        self._client = client
        self._store = store
        self._allowed_mentions = discord.AllowedMentions.none()
        if master.user_id is not None:
            self._allowed_mentions.users = [discord.Object(id=int(master.user_id))]
        self._scope: DiscordConversationScope | None = None
        self._is_forum = False
        self._lock = asyncio.Lock()
        self._confirmation: tuple[SpeechDeliveryPlan, PublishedSpeech] | None = None

    @property
    def webhook_id(self) -> int:
        """Return the identity used to distinguish our own webhook events."""
        return self._webhook.id

    @property
    def is_forum(self) -> bool:
        """Return whether the webhook targets a forum channel."""
        return self._is_forum

    async def initialize(self, guild_id: str) -> DiscordConversationScope:
        """Resolve one text or forum destination and reject a foreign guild."""
        async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
            webhook = await self._webhook.fetch(prefer_auth=False)
            if str(webhook.guild_id) != guild_id or webhook.channel_id is None:
                raise ValueError(
                    "Character webhook must belong to the configured guild."
                )
            channel = await self._client.fetch_channel(webhook.channel_id)
            if not isinstance(channel, (discord.TextChannel, discord.ForumChannel)):
                raise ValueError(
                    "Character webhook must target a text or forum channel."
                )
            if str(channel.guild.id) != guild_id:
                raise ValueError("Character channel belongs to a different guild.")
            self._is_forum = isinstance(channel, discord.ForumChannel)
            self._scope = DiscordConversationScope(
                guild_id=guild_id, channel_id=str(channel.id)
            )
            return self._scope

    def _validate_scope(
        self,
        scope: DiscordConversationScope,
        delivery_channel_id: str,
    ) -> None:
        if (
            self._scope is None
            or scope.guild_id != self._scope.guild_id
            or delivery_channel_id != self._scope.channel_id
            or (not self._is_forum and scope != self._scope)
        ):
            raise ValueError(
                "Response destination does not match the character channel."
            )

    async def _conversation_channel(
        self, scope: DiscordConversationScope
    ) -> discord.TextChannel | discord.Thread:
        """Fetch and validate the text channel or forum thread for a scope."""
        if self._scope is None:
            raise ValueError("Character webhook destination is not initialized.")
        parent_channel_id = self._scope.channel_id
        channel = await self._client.fetch_channel(int(scope.channel_id))
        if self._is_forum:
            if (
                not isinstance(channel, discord.Thread)
                or str(channel.parent_id) != parent_channel_id
            ):
                raise ValueError("The response thread is outside the character forum.")
            return channel
        if not isinstance(channel, discord.TextChannel):
            raise ValueError("The character destination is no longer a text channel.")
        return channel

    async def _check_destination(self, plan: SpeechDeliveryPlan) -> None:
        self._validate_scope(plan.conversation_scope, plan.delivery_channel_id)
        webhook = await self._webhook.fetch(prefer_auth=False)
        if self._scope is None or (str(webhook.guild_id), str(webhook.channel_id)) != (
            self._scope.guild_id,
            self._scope.channel_id,
        ):
            raise ValueError("The character webhook was moved to another destination.")
        await self._conversation_channel(plan.conversation_scope)

    async def _save(
        self, plan: SpeechDeliveryPlan, receipt: PublishedSpeech | None = None
    ) -> None:
        for attempt in range(3):
            try:
                async with asyncio.timeout(STORE_TIMEOUT_SECONDS):
                    result = await self._store.save(plan, receipt)
                if not is_err(result):
                    return
            except TimeoutError:
                pass
            if attempt < 2:
                await asyncio.sleep(0.5 * (2**attempt))
        raise RuntimeError(
            "Delivery progress could not be saved; confirmed parts will not be resent."
        )

    async def _flush_confirmation(self) -> None:
        if self._confirmation is not None:
            plan, receipt = self._confirmation
            await self._save(plan, receipt)
            self._confirmation = None

    @staticmethod
    def _receipt(
        message: discord.Message | discord.WebhookMessage, plan: SpeechDeliveryPlan
    ) -> PublishedSpeech:
        return PublishedSpeech(
            external_message_id=str(message.id),
            conversation_scope=DiscordConversationScope(
                guild_id=plan.conversation_scope.guild_id,
                channel_id=str(message.channel.id),
            ),
            external_sender_id=str(message.author.id),
            username=message.author.display_name,
            content=message.content,
            occurred_at=message.created_at,
            source_message_id=plan.source_message_id,
        )

    async def _find_confirmation(
        self, plan: SpeechDeliveryPlan
    ) -> PublishedSpeech | None:
        assert plan.attempt_started_at is not None
        channel = await self._conversation_channel(plan.conversation_scope)
        expected = plan.parts[len(plan.delivered)]
        confirmed_ids = {receipt.external_message_id for receipt in plan.delivered}
        async for message in channel.history(
            after=plan.attempt_started_at - timedelta(seconds=1),
            before=plan.attempt_started_at
            + timedelta(seconds=SEND_TIMEOUT_SECONDS + 5),
            oldest_first=True,
            limit=None,
        ):
            if (
                message.webhook_id == self.webhook_id
                and message.content == expected
                and str(message.id) not in confirmed_ids
            ):
                return self._receipt(message, plan)
        return None

    async def _record(
        self, plan: SpeechDeliveryPlan, receipt: PublishedSpeech
    ) -> SpeechDeliveryPlan:
        if receipt.conversation_scope != plan.conversation_scope:
            raise ValueError("Discord confirmed a message in an unexpected channel.")
        plan = replace(
            plan, delivered=(*plan.delivered, receipt), attempt_started_at=None
        )
        self._confirmation = (plan, receipt)
        await self._flush_confirmation()
        return plan

    async def _deliver(self, plan: SpeechDeliveryPlan) -> None:
        self._validate_scope(plan.conversation_scope, plan.delivery_channel_id)
        if plan.failure is not None:
            raise RuntimeError(plan.failure)
        if plan.complete:
            return
        async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
            await self._check_destination(plan)
            if plan.attempt_started_at is not None:
                receipt = await self._find_confirmation(plan)
                if receipt is None:
                    failure = "Previous delivery could not be confirmed; automatic resend was stopped."
                    await self._save(replace(plan, failure=failure))
                    raise RuntimeError(failure)
                plan = await self._record(plan, receipt)
        for part in plan.parts[len(plan.delivered) :]:
            plan = replace(plan, attempt_started_at=datetime.now(UTC))
            await self._save(plan)
            try:
                async with asyncio.timeout(SEND_TIMEOUT_SECONDS):
                    await self._check_destination(plan)
                    send_kwargs: dict[str, Any] = {
                        "content": part,
                        "username": plan.username,
                        "avatar_url": plan.avatar_url,
                        "allowed_mentions": self._allowed_mentions,
                        "wait": True,
                    }
                    if self._is_forum:
                        send_kwargs["thread"] = discord.Object(
                            id=int(plan.conversation_scope.channel_id)
                        )
                    message = await self._webhook.send(**send_kwargs)
                    if message is None:
                        raise RuntimeError("Discord did not return the sent message.")
                receipt = self._receipt(message, plan)
                plan = await self._record(plan, receipt)
            except discord.HTTPException as error:
                if 400 <= error.status < 500 and error.status != 429:
                    await self._save(
                        replace(
                            plan,
                            failure=f"Discord rejected delivery (HTTP {error.status}).",
                        )
                    )
                raise

    async def _recover_pending(self) -> None:
        await self._flush_confirmation()
        assert self._scope is not None
        pending = await self._store.pending(self._scope)
        if is_err(pending):
            raise RuntimeError("Pending delivery progress could not be read.")
        for plan in pending.value:
            if plan.failure is None:
                try:
                    await self._deliver(plan)
                except Exception:
                    latest = await self._store.get(plan.source_message_id)
                    if (
                        is_err(latest)
                        or latest.value is None
                        or latest.value.failure is None
                    ):
                        raise
                    logger.error(
                        "Stopped unconfirmed delivery for source %s: %s",
                        plan.source_message_id,
                        latest.value.failure,
                    )

    async def recover_pending(self) -> None:
        """Recover interrupted responses before accepting new requests."""
        async with asyncio.timeout(DELIVERY_TIMEOUT_SECONDS), self._lock:
            await self._recover_pending()

    @staticmethod
    def _error(error: Exception) -> SpeechPublishError:
        logger.error("Character delivery failed (%s)", type(error).__name__)
        return SpeechPublishError(
            type=SpeechPublishErrorType.INVALID_PAYLOAD
            if isinstance(error, ValueError)
            else SpeechPublishErrorType.DELIVERY_FAILED,
            message="Character delivery failed; confirmed parts are retained for recovery.",
        )

    async def resume(
        self,
        scope: DiscordConversationScope,
        source_message_id: str,
        delivery_channel_id: str,
    ) -> Result[bool, SpeechPublishError]:
        """Recover an existing plan without asking the model to regenerate it."""
        try:
            self._validate_scope(scope, delivery_channel_id)
            async with asyncio.timeout(DELIVERY_TIMEOUT_SECONDS), self._lock:
                if self._is_forum:
                    await self._conversation_channel(scope)
                await self._recover_pending()
                existing = await self._store.get(source_message_id)
                if is_err(existing):
                    raise RuntimeError("Response plan could not be read.")
                if existing.value is None:
                    return Ok(False)
                await self._deliver(existing.value)
                return Ok(True)
        except Exception as error:
            return Err(self._error(error))

    async def publish(
        self, message: CharacterSpeechMessage
    ) -> Result[None, SpeechPublishError]:
        """Publish paragraph-sized parts in order, recording each before sending the next."""
        try:
            self._validate_scope(
                message.conversation_scope, message.delivery_channel_id
            )
            if (
                not message.content.strip()
                or not message.source_message_id.isascii()
                or not message.source_message_id.isdecimal()
                or len(message.source_message_id) > 20
            ):
                raise ValueError(
                    "Response content and source message identity are required."
                )
            async with asyncio.timeout(DELIVERY_TIMEOUT_SECONDS), self._lock:
                await self._recover_pending()
                existing = await self._store.get(message.source_message_id)
                if is_err(existing):
                    raise RuntimeError("Response plan could not be read.")
                plan = existing.value
                if plan is None:
                    scope = message.conversation_scope
                    parts = split_discord_content(message.content, limit=1850)
                    plan = SpeechDeliveryPlan(
                        source_message_id=message.source_message_id,
                        conversation_scope=scope,
                        username=message.username,
                        avatar_url=message.avatar_url,
                        parts=parts,
                        delivery_channel_id=message.delivery_channel_id,
                    )
                    await self._save(plan)
                await self._deliver(plan)
            return Ok(None)
        except Exception as error:
            return Err(self._error(error))


class DiscordWebhookSpeechPublisherRouter(ISpeechPublisher):
    """Route character speech to one of several channel-bound webhooks."""

    def __init__(self, publishers: dict[str, DiscordWebhookSpeechPublisher]) -> None:
        self._publishers = dict(publishers)

    async def recover_pending(self) -> None:
        """Recover pending deliveries for every configured webhook."""
        for publisher in self._publishers.values():
            await publisher.recover_pending()

    @staticmethod
    def _destination_error() -> Err[SpeechPublishError]:
        return Err(
            SpeechPublishError(
                type=SpeechPublishErrorType.INVALID_PAYLOAD,
                message="Response destination is not configured.",
            )
        )

    async def resume(
        self,
        scope: DiscordConversationScope,
        source_message_id: str,
        delivery_channel_id: str,
    ) -> Result[bool, SpeechPublishError]:
        """Resume a response through its configured webhook destination."""
        publisher = self._publishers.get(delivery_channel_id)
        if publisher is None:
            return self._destination_error()
        return await publisher.resume(scope, source_message_id, delivery_channel_id)

    async def publish(
        self, message: CharacterSpeechMessage
    ) -> Result[None, SpeechPublishError]:
        """Publish a response through its configured webhook destination."""
        publisher = self._publishers.get(message.delivery_channel_id)
        if publisher is None:
            return self._destination_error()
        return await publisher.publish(message)
