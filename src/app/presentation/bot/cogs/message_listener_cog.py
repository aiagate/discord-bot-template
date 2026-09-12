"""Persist Discord messages and run a bounded FIFO of character responses."""

import asyncio
import logging
import re
from collections.abc import Awaitable, Callable
from contextlib import suppress
from dataclasses import dataclass

import discord
from discord.ext import commands
from flow_res import is_err

from app.application.mediator import ApplicationMediator
from app.contracts.messages.times_message import TimesEpisodePlan
from app.contracts.ports.times_episode_store import ITimesEpisodeStore
from app.domain.value_objects import AuthorKind, DiscordConversationScope
from app.presentation.bot.cogs.base_cog import BaseCog
from app.usecases.chat.generate_character_response import (
    GenerateCharacterResponseCommand,
)
from app.usecases.chat.generate_times_episode import (
    GenerateTimesEpisodeCommand,
)
from app.usecases.chat.save_discord_chat import SaveDiscordChatCommand

logger = logging.getLogger(__name__)
MAX_PENDING_RESPONSES = 10
MAX_QUEUE_WAIT_SECONDS = 120.0
RESPONSE_TIMEOUT_SECONDS = 210.0
SAVE_TIMEOUT_SECONDS = 10.0
NOTICE_TIMEOUT_SECONDS = 5.0


@dataclass(frozen=True, slots=True)
class DiscordResponseDestination:
    """A configured channel-bound webhook used by the response listener."""

    scope: DiscordConversationScope
    webhook_id: int
    is_forum: bool


@dataclass(frozen=True, slots=True)
class DiscordTimesDestination:
    """A configured text-channel webhook destination for Times episodes."""

    scope: DiscordConversationScope
    webhook_id: int


@dataclass(frozen=True)
class _QueuedResponse:
    command: GenerateCharacterResponseCommand
    message: discord.Message
    expires_at: float


def _message_text(message: discord.Message) -> str:
    pieces = [message.content] if message.content else []
    for embed in message.embeds:
        for value in (embed.title, embed.description):
            if value:
                pieces.append(value)
        for field in embed.fields:
            if field.name and field.value:
                pieces.append(f"{field.name}: {field.value}")
    return "\n".join(pieces)


class DiscordMessageListenerCog(BaseCog, name="Discord Message Listener"):
    """Persist guild messages and answer users or external webhooks."""

    def __init__(
        self,
        bot: commands.Bot,
        mediator: ApplicationMediator,
        *,
        ai_response_destinations: tuple[DiscordResponseDestination, ...] = (),
        times_destination: DiscordTimesDestination | None = None,
        times_store: ITimesEpisodeStore | None = None,
        work_handler: Callable[[discord.Message], Awaitable[bool]] | None = None,
        ignored_webhook_ids: tuple[int, ...] = (),
    ) -> None:
        super().__init__(bot, mediator)
        self._destinations = ai_response_destinations
        self._main_text_destination = next(
            (
                destination
                for destination in ai_response_destinations
                if not destination.is_forum
            ),
            None,
        )
        self._times_destination = times_destination
        self._times_store = times_store
        self._work_handler = work_handler
        webhook_ids = [
            *ignored_webhook_ids,
            *(dest.webhook_id for dest in ai_response_destinations),
        ]
        if times_destination is not None:
            webhook_ids.append(times_destination.webhook_id)
        self._webhook_ids = frozenset(webhook_ids)
        self._queue: asyncio.Queue[_QueuedResponse] = asyncio.Queue(
            maxsize=MAX_PENDING_RESPONSES
        )
        self._times_queue: asyncio.Queue[GenerateTimesEpisodeCommand] = asyncio.Queue(
            maxsize=MAX_PENDING_RESPONSES
        )
        self._ingest_lock = asyncio.Lock()
        self._worker: asyncio.Task[None] | None = None
        self._times_worker: asyncio.Task[None] | None = None
        self._overloaded = False

    async def cog_load(self) -> None:
        """Start one consumer so parts from separate responses never interleave."""
        if self._destinations:
            self._worker = asyncio.create_task(
                self._consume(), name="character-responses"
            )
        if self._times_destination is not None:
            self._times_worker = asyncio.create_task(
                self._consume_times(), name="times-episodes"
            )
            await self._recover_times_queue()

    async def _recover_times_queue(self) -> None:
        """Requeue durable Times episodes that were not consumed before a restart."""
        if self._times_store is None or self._times_destination is None:
            return
        try:
            pending = await self._times_store.pending(self._times_destination.scope)
        except Exception:
            logger.exception("Could not read pending Times episodes")
            return
        if is_err(pending):
            logger.error(
                "Could not read pending Times episodes: %s", pending.error.message
            )
            return
        for plan in pending.value:
            await self._times_queue.put(
                GenerateTimesEpisodeCommand(
                    source_message_id=plan.source_message_id,
                    guild_id=plan.guild_id,
                    channel_id=plan.channel_id,
                    delivery_channel_id=plan.delivery_channel_id,
                )
            )

    async def cog_unload(self) -> None:
        """Cancel the consumers before the SDK clients close."""
        if self._worker is not None:
            self._worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._worker
            self._worker = None
        if self._times_worker is not None:
            self._times_worker.cancel()
            with suppress(asyncio.CancelledError):
                await self._times_worker
            self._times_worker = None
        while not self._queue.empty():
            self._queue.get_nowait()
            self._queue.task_done()
        while not self._times_queue.empty():
            self._times_queue.get_nowait()
            self._times_queue.task_done()

    async def _notify(self, message: discord.Message, content: str) -> None:
        try:
            async with asyncio.timeout(NOTICE_TIMEOUT_SECONDS):
                await message.reply(
                    content,
                    mention_author=False,
                    allowed_mentions=discord.AllowedMentions.none(),
                )
        except (discord.HTTPException, TimeoutError):
            logger.warning(
                "Could not notify message %s in channel %s",
                message.id,
                message.channel.id,
            )

    async def _consume(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                if asyncio.get_running_loop().time() >= item.expires_at:
                    await self._notify(
                        item.message,
                        "応答待ちの期限を超えました。必要であれば、もう一度お送りください。",
                    )
                    continue
                async with asyncio.timeout(RESPONSE_TIMEOUT_SECONDS):
                    result = await self.mediator.send_async(item.command)
                if is_err(result):
                    logger.error(
                        "Character response failed for message %s: %s",
                        item.message.id,
                        result.error.message,
                    )
                    await self._notify(item.message, result.error.display_message)
            except TimeoutError:
                await self._notify(
                    item.message,
                    "応答処理の期限を超えました。送信済みの部分は再送しません。",
                )
            except Exception:
                logger.exception(
                    "Character response failed for message %s", item.message.id
                )
                await self._notify(item.message, "応答処理に失敗しました。")
            finally:
                self._queue.task_done()

    async def _consume_times(self) -> None:
        while True:
            command = await self._times_queue.get()
            try:
                async with asyncio.timeout(RESPONSE_TIMEOUT_SECONDS):
                    result = await self.mediator.send_async(command)
                if is_err(result):
                    logger.error(
                        "Times episode generation failed for message %s: %s",
                        command.source_message_id,
                        result.error.message,
                    )
            except TimeoutError:
                logger.warning(
                    "Times episode timed out for source message %s",
                    command.source_message_id,
                )
            except Exception:
                logger.exception(
                    "Times episode failed unexpectedly for source message %s",
                    command.source_message_id,
                )
            finally:
                self._times_queue.task_done()

    def _response_target(
        self,
        message: discord.Message,
        scope: DiscordConversationScope,
    ) -> tuple[DiscordConversationScope, str] | None:
        """Return the conversation and delivery scopes for an AI-target message."""
        for destination in self._destinations:
            if scope.guild_id != destination.scope.guild_id:
                continue
            if destination.is_forum:
                if (
                    isinstance(message.channel, discord.Thread)
                    and str(message.channel.parent_id) == destination.scope.channel_id
                ):
                    return scope, destination.scope.channel_id
            elif scope == destination.scope:
                return scope, destination.scope.channel_id
        if (
            message.webhook_id is not None
            and self._main_text_destination is not None
            and scope.guild_id == self._main_text_destination.scope.guild_id
        ):
            destination = self._main_text_destination
            logger.debug(
                "Routing external webhook message %s from channel %s to main text "
                "channel %s",
                message.id,
                scope.channel_id,
                destination.scope.channel_id,
            )
            return destination.scope, destination.scope.channel_id
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Save guild messages and queue responses in configured destinations."""
        if message.author == self.bot.user:
            return
        if message.webhook_id is not None and message.webhook_id in self._webhook_ids:
            return
        if message.guild is None:
            return
        scope = DiscordConversationScope(
            guild_id=str(message.guild.id), channel_id=str(message.channel.id)
        )
        response_target = self._response_target(message, scope)
        if response_target is not None:
            response_scope, delivery_channel_id = response_target
            # Saving and enqueueing share the receive order; generation holds no DB lock.
            async with self._ingest_lock:
                await self._save_and_route(message, response_scope, delivery_channel_id)
        else:
            await self._save_and_route(message, scope, None)

    async def _save_and_route(
        self,
        message: discord.Message,
        scope: DiscordConversationScope,
        delivery_channel_id: str | None,
    ) -> None:
        content = _message_text(message)
        is_webhook = message.webhook_id is not None
        is_bot = message.author.bot and not is_webhook
        if is_webhook:
            author_kind = AuthorKind.WEBHOOK
        elif is_bot:
            author_kind = AuthorKind.BOT
        else:
            author_kind = AuthorKind.USER
        reference = message.reference
        reply_to = (
            str(reference.message_id)
            if reference is not None and reference.message_id is not None
            else None
        )
        try:
            async with asyncio.timeout(SAVE_TIMEOUT_SECONDS):
                saved = await self.mediator.send_async(
                    SaveDiscordChatCommand(
                        external_sender_id=(
                            str(message.webhook_id)
                            if message.webhook_id is not None
                            else str(message.author.id)
                        ),
                        guild_id=scope.guild_id,
                        channel_id=scope.channel_id,
                        content=content,
                        occurred_at=message.created_at,
                        author_kind=author_kind,
                        external_message_id=str(message.id),
                        author_name=message.author.display_name,
                        reply_to_external_message_id=reply_to,
                    )
                )
        except TimeoutError:
            await self._notify(message, "メッセージの保存がタイムアウトしました。")
            return
        if is_err(saved):
            await self._notify(message, "メッセージの保存に失敗しました。")
            return
        if not is_bot and content.strip() and self._work_handler is not None:
            try:
                if await self._work_handler(message):
                    return
            except Exception:
                logger.exception(
                    "Could not route character work for message %s", message.id
                )
                await self._notify(
                    message,
                    "作業の受付を確認できませんでした。状態を確認してください。",
                )
                return

        times_candidate = (
            self._times_destination is not None
            and author_kind is AuthorKind.USER
            and scope.guild_id == self._times_destination.scope.guild_id
            and bool(content.strip())
        )
        if (
            not is_webhook
            and not is_bot
            and (delivery_channel_id is not None or times_candidate)
        ):
            context = await self.bot.get_context(message)
            if context.prefix is not None:
                return
        if self.bot.user is not None:
            content = re.sub(rf"<@!?{self.bot.user.id}>", "", content).strip()
        if not content:
            return
        if (
            self._times_destination is not None
            and author_kind is AuthorKind.USER
            and scope.guild_id == self._times_destination.scope.guild_id
        ):
            times_command = GenerateTimesEpisodeCommand(
                source_message_id=str(message.id),
                guild_id=scope.guild_id,
                channel_id=scope.channel_id,
                delivery_channel_id=self._times_destination.scope.channel_id,
            )
            if self._times_store is not None:
                pending_plan = TimesEpisodePlan(
                    source_message_id=str(message.id),
                    guild_id=scope.guild_id,
                    channel_id=scope.channel_id,
                    delivery_channel_id=self._times_destination.scope.channel_id,
                    posts=(),
                    status="PENDING",
                    next_post_index=0,
                )
                try:
                    saved_plan = await self._times_store.save(pending_plan)
                    if is_err(saved_plan):
                        logger.error(
                            "Could not persist Times episode for message %s: %s",
                            message.id,
                            saved_plan.error.message,
                        )
                except Exception:
                    logger.exception(
                        "Could not persist Times episode for message %s", message.id
                    )
            # Durable plans make backpressure safe: keep accepting the episode
            # once a worker slot is available instead of leaving it for a restart.
            await self._times_queue.put(times_command)

        if delivery_channel_id is None or is_bot:
            return
        item = _QueuedResponse(
            command=GenerateCharacterResponseCommand(
                content=content,
                guild_id=scope.guild_id,
                channel_id=scope.channel_id,
                source_message_id=saved.value.id,
                delivery_channel_id=delivery_channel_id,
            ),
            message=message,
            expires_at=asyncio.get_running_loop().time() + MAX_QUEUE_WAIT_SECONDS,
        )
        try:
            self._queue.put_nowait(item)
            self._overloaded = False
        except asyncio.QueueFull:
            if not self._overloaded:
                self._overloaded = True
                await self._notify(
                    message,
                    "応答待ちが上限に達しています。この投稿は保存し、後の会話で参照します。",
                )
