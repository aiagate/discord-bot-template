"""One Discord bot receives normal speech; character webhooks deliver replies."""

import asyncio
import json
import logging
import os
import time
from contextlib import ExitStack

import aiohttp
import discord
from discord.ext import commands

from app.application.collective_settings import BotCollectiveConfig, load_characters
from app.infrastructure.collective.codex import CodexWorker
from app.infrastructure.collective.gemini import GeminiConversation
from app.infrastructure.collective.store import SQLiteCollectiveStore
from app.infrastructure.collective.webhook import WebhookPublisher
from app.infrastructure.collective.workspace import CharacterWorkspaces
from app.usecases.collective.delivery import Delivery
from app.usecases.collective.runtime import Collective

logger = logging.getLogger(__name__)


class CollectiveCog(commands.Cog):
    """Run conversation, serial work, and delivery as three independent tasks."""

    def __init__(self, bot: commands.Bot, config: BotCollectiveConfig) -> None:
        self.bot = bot
        self.config = config
        self.stack = ExitStack()
        self.session: aiohttp.ClientSession | None = None
        self.collective: Collective | None = None
        self.delivery: Delivery | None = None
        self.tasks: list[asyncio.Task[None]] = []
        self.webhook_ids: set[int] = set()

    async def cog_load(self) -> None:
        """Start only after Discord channel and webhook validation can run."""
        self.tasks.append(asyncio.create_task(self._start(), name="collective-start"))

    async def _start(self) -> None:
        await self.bot.wait_until_ready()
        try:
            if not self.bot.intents.message_content:
                raise ValueError("The Message Content Intent is required")
            config = self.config
            store = SQLiteCollectiveStore(config.root)
            self.stack.enter_context(store.lock())
            self.session = aiohttp.ClientSession(
                timeout=aiohttp.ClientTimeout(total=120)
            )
            master_webhook = os.environ.get(config.master_webhook_env)
            if master_webhook is None:
                pool = json.loads(
                    os.environ.get("DISCORD_CHARACTER_WEBHOOK_URLS_JSON", "[]")
                )
                if (
                    not isinstance(pool, list)
                    or not pool
                    or not isinstance(pool[0], str)
                    or not pool[0].strip()
                ):
                    raise ValueError(
                        "A master webhook or nonempty webhook pool is required"
                    )
                master_webhook = pool[0]
            destinations = {
                "master": master_webhook,
                "times": os.environ[config.times_webhook_env],
            }
            for scope, channel_id in (
                ("master", config.master_channel_id),
                ("times", config.times_channel_id),
            ):
                channel = self.bot.get_channel(channel_id)
                if (
                    not isinstance(channel, discord.TextChannel)
                    or channel.guild.id != config.guild_id
                ):
                    raise ValueError(
                        "Configured channels must be text channels in the configured guild"
                    )
                member = channel.guild.me
                permissions = channel.permissions_for(member)
                if not permissions.view_channel or not permissions.read_message_history:
                    raise ValueError(
                        "The bot needs View Channel and Read Message History"
                    )
                async with self.session.get(
                    destinations[scope], allow_redirects=False
                ) as response:
                    if response.status != 200:
                        raise ValueError("Configured webhook cannot be read")
                    value = await response.json()
                    if str(value.get("channel_id")) != str(channel_id):
                        raise ValueError(
                            "Configured webhook belongs to the wrong channel"
                        )
                    self.webhook_ids.add(int(value["id"]))
            characters = load_characters(config.root)
            master = (config.root / "master.md").read_text()
            conversation = GeminiConversation(
                self.session,
                os.environ[config.gemini_key_env],
                config.gemini_model,
                config.max_output_tokens,
                config.token_margin,
            )
            codex = CodexWorker(
                config.agy_skill, config.codex_model, config.settings.guide_bytes
            )
            self.collective = Collective(
                store,
                characters,
                master,
                conversation,
                codex,
                CharacterWorkspaces(
                    config.root, config.agy_skill, config.settings.guide_bytes
                ),
                config.root,
                config.settings,
            )
            self.delivery = Delivery(
                store,
                WebhookPublisher(self.session, destinations),
                characters,
                config.settings,
            )
            await self.collective.recover(time.time())
            self.delivery.recover()
            for lane in ("conversation", "work", "delivery"):
                self.tasks.append(
                    asyncio.create_task(self._loop(lane), name=f"collective-{lane}")
                )
        except Exception:
            logger.exception("Collective startup failed")
            await self._close_resources()

    async def _loop(self, lane: str) -> None:
        assert self.collective is not None and self.delivery is not None
        if lane == "conversation":
            try:
                await self.collective.validate_inputs(time.time())
            except Exception:
                logger.exception(
                    "Startup input validation failed; turns retain bounded retries"
                )
        while True:
            try:
                now = time.time()
                if lane == "conversation":
                    self.collective.schedule(now)
                    await self.collective.conversation_step(now)
                elif lane == "work":
                    await self.collective.work_step(now)
                else:
                    await self.delivery.step(now)
            except Exception:
                logger.exception("Collective %s lane failed", lane)
            await asyncio.sleep(self.config.settings.poll_seconds)

    async def _close_resources(self) -> None:
        if self.session is not None:
            await self.session.close()
        self.stack.close()

    async def cog_unload(self) -> None:
        """Cancel consumers and confirm work termination before releasing the lock."""
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        if self.collective is not None:
            for turn in self.collective.store.read().turns.values():
                if turn.lane == "work" and turn.status == "running":
                    if not await self.collective.codex.interrupt(turn.id):
                        raise RuntimeError(
                            "Work termination unconfirmed; retain the runner lock"
                        )
        await self._close_resources()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Accept unmentioned master speech and ignore bot/webhook echoes."""
        if (
            self.collective is None
            or message.author.bot
            or message.webhook_id is not None
        ):
            return
        if (
            message.author.id != self.config.master_id
            or message.guild is None
            or message.guild.id != self.config.guild_id
        ):
            return
        if message.channel.id not in {
            self.config.master_channel_id,
            self.config.times_channel_id,
        }:
            return
        if message.content == "!maid" or message.content.startswith("!maid "):
            return
        named = [
            character.id
            for character in self.collective.characters.values()
            if character.id.casefold() in message.content.casefold()
            or character.name.split("【", 1)[0].casefold() in message.content.casefold()
        ]
        self.collective.receive(
            str(message.id),
            message.content,
            "times" if message.channel.id == self.config.times_channel_id else "master",
            message.created_at.timestamp(),
            named[0] if len(named) == 1 else None,
            message.jump_url,
        )

    @commands.group(name="maid", invoke_without_command=True)
    async def maid(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show administrative status without requiring a model response."""
        if ctx.author.id != self.config.master_id or self.collective is None:
            return
        state = self.collective.store.read()
        lines = [
            f"{activity.id}: {activity.status} — {activity.objective}"
            for activity in state.activities.values()
        ]
        lines += [
            f"配信確認: {part.id}"
            for part in state.parts.values()
            if part.status == "unknown"
        ]
        lines += [
            f"配信再試行: {part.id} — {part.error}"
            for part in state.parts.values()
            if part.status in {"rejected", "held"}
        ]
        await ctx.send("\n".join(lines)[:1900] or "活動はありません。")

    @maid.command(name="stop")
    async def maid_stop(
        self, ctx: commands.Context[commands.Bot], activity_id: str
    ) -> None:
        """Provide an explicit stop path even when conversational input is held."""
        if ctx.author.id != self.config.master_id or self.collective is None:
            return
        await self.collective.stop(activity_id, ctx.message.content, time.time())
        await ctx.send("停止を記録しました。実行済みの操作は取り消していません。")

    @maid.command(name="confirm")
    async def maid_confirm(
        self, ctx: commands.Context[commands.Bot], part_id: str, message_id: str
    ) -> None:
        """Queue known-ID delivery reconciliation without blindly resending."""
        if ctx.author.id != self.config.master_id or self.delivery is None:
            return
        self.delivery.confirm(part_id, message_id)
        await ctx.send("投稿IDの照合を受け付けました。")

    @maid.command(name="retry")
    async def maid_retry(
        self, ctx: commands.Context[commands.Bot], part_id: str
    ) -> None:
        """Retry a definitely rejected delivery via management command."""
        if ctx.author.id != self.config.master_id or self.delivery is None:
            return
        self.delivery.retry(part_id)
        await ctx.send("保存済みの本文で再試行します。")
