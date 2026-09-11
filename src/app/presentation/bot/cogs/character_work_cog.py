"""Discord controls and progress delivery for character work."""

import logging
import re
from typing import Any

import discord
from discord.ext import commands
from flow_res import is_err

from app.application.character_work_settings import CharacterWorkSettings
from app.application.mediator import ApplicationMediator
from app.contracts.messages.character_work import CharacterWork, CharacterWorkError
from app.contracts.ports.character_work import (
    ICharacterWorkExecutor,
    ICharacterWorkReporter,
    ICharacterWorkStore,
)
from app.domain.characters import CharacterRoster
from app.domain.value_objects import AuthorKind
from app.presentation.bot.cogs.base_cog import BaseCog
from app.usecases.chat.character_work import CharacterWorkService, WorkResult
from app.usecases.chat.save_discord_chat import SaveDiscordChatCommand

logger = logging.getLogger(__name__)
_STATUS = {
    "queued": "準備中",
    "running": "作業中",
    "completed": "完了",
    "stopped": "中止",
    "failed": "失敗",
    "paused": "中断",
}


class CharacterWorkCog(BaseCog, name="Character Work"):
    """Accept work from configured users in channels with reporting webhooks."""

    def __init__(
        self,
        bot: commands.Bot,
        mediator: ApplicationMediator,
        settings: CharacterWorkSettings,
        roster: CharacterRoster,
        store: ICharacterWorkStore,
        executor: ICharacterWorkExecutor,
        reporter: ICharacterWorkReporter,
    ) -> None:
        super().__init__(bot, mediator)
        self._settings = settings
        self._executor = executor
        self._reporter = reporter
        self._characters = {item.character_id: item for item in roster.characters}
        self._names = {
            name.casefold(): item.character_id
            for item in roster.characters
            for name in (item.name, item.character_id)
        }
        self._service = CharacterWorkService(
            store,
            executor,
            roster,
            timeout_seconds=settings.timeout_seconds,
            on_update=self._publish,
        )

    async def cog_load(self) -> None:
        """Restore task links before accepting Discord messages."""
        await self._service.initialize()

    async def cog_unload(self) -> None:
        """Interrupt runtimes and persist their resumable identities."""
        await self._service.close()

    def _allowed(self, message: discord.Message) -> bool:
        if (
            message.guild is None
            or str(message.guild.id) != self._settings.guild_id
            or str(message.author.id) not in self._settings.user_ids
            or message.author.bot
            or message.webhook_id is not None
        ):
            return False
        channel = message.channel
        return str(channel.id) in self._settings.channel_ids or (
            isinstance(channel, discord.Thread)
            and str(channel.parent_id) in self._settings.channel_ids
        )

    def _current(self, message: discord.Message) -> CharacterWork | None:
        if message.guild is None:
            return None
        return self._service.current(
            str(message.guild.id), str(message.channel.id), str(message.author.id)
        )

    def cog_check(self, ctx: commands.Context[Any]) -> bool:
        """Apply the same access check to every work subcommand."""
        return self._allowed(ctx.message)

    async def cog_command_error(
        self, ctx: commands.Context[commands.Bot], error: Exception
    ) -> None:
        """Explain access denial without revealing work in another conversation."""
        if isinstance(error, commands.CheckFailure):
            await ctx.send("このユーザー・チャンネルでは作業を依頼できません。")
            return
        await super().cog_command_error(ctx, error)

    async def handle_message(self, message: discord.Message) -> bool:
        """Route ordinary conversation to a named or already linked worker."""
        if not self._allowed(message):
            return False
        context = await self.bot.get_context(message)
        if context.prefix is not None:
            return False
        prompt = message.content.strip()
        if not prompt:
            return False
        match = re.match(r"^([^\s、,:：]+)[\s、,:：]+(.+)$", prompt, re.DOTALL)
        character_id = self._names.get(match[1].casefold()) if match else None
        current = self._current(message)
        if character_id is not None and match is not None:
            prompt = match[2].strip()
            if current is None or current.character_id != character_id:
                await self._submit(message, character_id, prompt)
                return True
        if current is None:
            return False
        assert message.guild is not None
        result = await self._service.follow_up(
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            owner_id=str(message.author.id),
            message_id=str(message.id),
            prompt=prompt,
        )
        await self._acknowledge(message, result, "追加指示を受け付けました。")
        return True

    async def _submit(
        self, message: discord.Message, character_id: str, prompt: str
    ) -> None:
        assert message.guild is not None
        result = await self._service.start(
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            owner_id=str(message.author.id),
            message_id=str(message.id),
            character_id=character_id,
            prompt=prompt,
        )
        await self._acknowledge(message, result, "作業を受け付けました。")

    async def _acknowledge(
        self, message: discord.Message, result: WorkResult, text: str
    ) -> None:
        if is_err(result):
            content = str(result.error)
        else:
            task = result.value
            name = self._characters[task.character_id].name
            content = f"{name}: {text}（作業 {task.id}）"
        await message.reply(
            content,
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @commands.group(name="work", invoke_without_command=True)
    async def work(
        self,
        ctx: commands.Context[commands.Bot],
        character: str = "",
        *,
        prompt: str = "",
    ) -> None:
        """Start a new task with any registered character: !work <name> <request>."""
        character_id = self._names.get(character.casefold())
        if character_id is None or not prompt.strip():
            await ctx.send(
                "`!work キャラクター名 依頼` で開始します。全員に調査・実装を依頼できます。追加指示は通常の発言で送れます。`!work status` / `!work stop` / `!work result` / `!work chat` も使えます。"
            )
            return
        await self._submit(ctx.message, character_id, prompt)

    @work.command(name="status")
    async def work_status(self, ctx: commands.Context[commands.Bot]) -> None:
        """Show this owner's work status in the current conversation."""
        task = self._current(ctx.message)
        if task is None:
            await ctx.send("この会話で依頼した作業がありません。")
            return
        await ctx.send(
            f"作業 {task.id} · {_STATUS[task.status]}\n{task.summary[:1500]}",
            allowed_mentions=discord.AllowedMentions.none(),
        )

    @work.command(name="stop")
    async def work_stop(self, ctx: commands.Context[commands.Bot]) -> None:
        """Stop running work while keeping its session available for follow-up."""
        await self._stop(ctx, unlink=False)

    @work.command(name="chat")
    async def work_chat(self, ctx: commands.Context[commands.Bot]) -> None:
        """Stop work and return ordinary messages to character chat."""
        await self._stop(ctx, unlink=True)

    async def _stop(self, ctx: commands.Context[commands.Bot], *, unlink: bool) -> None:
        if ctx.guild is None:
            return
        result = await self._service.stop(
            str(ctx.guild.id),
            str(ctx.channel.id),
            str(ctx.author.id),
            unlink=unlink,
        )
        await self._acknowledge(
            ctx.message,
            result,
            "会話に戻りました。" if unlink else "作業を中止しました。",
        )

    @work.command(name="result")
    async def work_result(self, ctx: commands.Context[commands.Bot]) -> None:
        """Retrieve the most recently saved result, including after a restart."""
        task = self._current(ctx.message)
        if task is None or not task.result:
            await ctx.send("保存された作業結果はまだありません。")
            return
        try:
            await self._send(task, task.result, persist=False, include_artifacts=True)
        except CharacterWorkError as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())

    async def _publish(self, task: CharacterWork) -> None:
        await self._send(
            task,
            task.result if task.status == "completed" else task.summary,
            persist=task.status == "completed",
            include_artifacts=task.status == "completed",
        )

    async def _send(
        self,
        task: CharacterWork,
        text: str,
        *,
        persist: bool,
        include_artifacts: bool = False,
    ) -> None:
        attachments = (
            await self._executor.attachments(task) if include_artifacts else ()
        )
        if include_artifacts and task.artifacts is not None:
            text = f"{task.artifacts.summary}\n\n{text}"
        receipt = await self._reporter.send(
            task,
            self._characters[task.character_id],
            text,
            attachments,
        )
        if persist:
            saved = await self.mediator.send_async(
                SaveDiscordChatCommand(
                    external_sender_id=receipt.external_sender_id,
                    guild_id=task.guild_id,
                    channel_id=task.channel_id,
                    content=text,
                    occurred_at=receipt.occurred_at,
                    author_kind=AuthorKind.BOT,
                    external_message_id=receipt.external_message_id,
                    author_name=receipt.username,
                )
            )
            if is_err(saved):
                logger.error("Could not save work result %s in chat history", task.id)
