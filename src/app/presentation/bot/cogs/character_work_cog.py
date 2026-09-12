"""Discord controls and progress delivery for character work."""

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

import discord
from discord.ext import commands
from flow_res import is_err

from app.application.character_work_settings import CharacterWorkSettings
from app.application.mediator import ApplicationMediator
from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkAttachment,
)
from app.contracts.ports.character_work import (
    ICharacterWorkExecutor,
    ICharacterWorkReporter,
    ICharacterWorkStore,
)
from app.domain.characters import CharacterDefinition, CharacterRoster
from app.presentation.bot.cogs.base_cog import BaseCog
from app.usecases.chat.character_work import CharacterWorkService, WorkResult

logger = logging.getLogger(__name__)
_STATUS = {
    "queued": "準備中",
    "running": "作業中",
    "completed": "完了",
    "stopped": "中止",
    "failed": "失敗",
    "paused": "中断",
}
_CHARACTER_PREFIX = re.compile(r"^([^\s、,:：]+)[\s、,:：]+(.+)$", re.DOTALL)
_EXPLICIT_WORK_PREFIX = re.compile(
    r"^(?:作業|依頼|タスク)[\s]*[:：][\s]*(.+)$", re.DOTALL
)
_WORK_REQUEST_MARKERS = (
    "調べて",
    "調査して",
    "実装して",
    "作成して",
    "修正して",
    "検証して",
    "比較して",
    "分析して",
    "まとめて",
    "確認して",
    "書いて",
    "直して",
    "作って",
    "お願い",
    "依頼",
)
WorkReviewer = Callable[
    [CharacterWork, CharacterDefinition, tuple[WorkAttachment, ...]],
    Awaitable[str | None],
]


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
        reviewer: WorkReviewer | None = None,
    ) -> None:
        super().__init__(bot, mediator)
        self._settings = settings
        self._executor = executor
        self._reporter = reporter
        self._reviewer = reviewer
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
        """Start or steer work without consuming the ordinary Gemini response."""
        if not self._allowed(message):
            return False
        context = await self.bot.get_context(message)
        if context.prefix is not None:
            return False
        prompt = message.content.strip()
        if not prompt:
            return False
        current = self._current(message)
        match = _CHARACTER_PREFIX.match(prompt)
        character_id = self._names.get(match[1].casefold()) if match else None
        if character_id is not None and match is not None:
            request = match[2].strip()
            work_prompt = self._work_prompt(request)
            if work_prompt is not None and (
                current is None or current.character_id != character_id
            ):
                return await self._submit(message, character_id, work_prompt)
        else:
            work_prompt = self._work_prompt(prompt)
        if current is None or work_prompt is None:
            return False
        assert message.guild is not None
        result = await self._service.follow_up(
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            owner_id=str(message.author.id),
            message_id=str(message.id),
            prompt=work_prompt,
        )
        return await self._report_error(message, result)

    @staticmethod
    def _work_prompt(prompt: str) -> str | None:
        """Recognize an explicit work request while leaving casual chat to Gemini."""
        explicit = _EXPLICIT_WORK_PREFIX.match(prompt)
        if explicit is not None:
            value = explicit[1].strip()
            return value or None
        if any(marker in prompt for marker in _WORK_REQUEST_MARKERS):
            return prompt
        return None

    async def _submit(
        self, message: discord.Message, character_id: str, prompt: str
    ) -> bool:
        assert message.guild is not None
        result = await self._service.start(
            guild_id=str(message.guild.id),
            channel_id=str(message.channel.id),
            owner_id=str(message.author.id),
            message_id=str(message.id),
            character_id=character_id,
            prompt=prompt,
        )
        return await self._report_error(message, result)

    async def _report_error(self, message: discord.Message, result: WorkResult) -> bool:
        """Show only rejected work requests in the control conversation."""
        if not is_err(result):
            return False
        await message.reply(
            str(result.error),
            mention_author=False,
            allowed_mentions=discord.AllowedMentions.none(),
        )
        return True

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
                "`!work キャラクター名 依頼` で開始します。全員に調査・実装を依頼できます。追加指示は `作業: 指示` または調査・実装などの依頼文で送れます。雑談はGeminiへ渡されます。`!work status` / `!work stop` / `!work result` / `!work chat` も使えます。"
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
        if is_err(result):
            await self._report_error(ctx.message, result)
            return
        await self._publish(result.value)

    @work.command(name="result")
    async def work_result(self, ctx: commands.Context[commands.Bot]) -> None:
        """Retrieve the most recently saved result, including after a restart."""
        task = self._current(ctx.message)
        if task is None or not task.result:
            await ctx.send("保存された作業結果はまだありません。")
            return
        try:
            await self._deliver(task)
        except CharacterWorkError as error:
            await ctx.send(str(error), allowed_mentions=discord.AllowedMentions.none())

    async def _publish(self, task: CharacterWork) -> None:
        await self._deliver(task)

    async def _deliver(self, task: CharacterWork) -> None:
        """Review completed evidence and publish only the character-facing report."""
        attachments = (
            await self._executor.attachments(task) if task.status == "completed" else ()
        )
        if (
            task.status == "completed"
            and not task.review
            and self._reviewer is not None
        ):
            try:
                review = await self._reviewer(
                    task, self._characters[task.character_id], attachments
                )
            except Exception:
                logger.exception("Could not review completed work %s", task.id)
            else:
                if review is not None:
                    saved = await self._service.save_review(task.id, review)
                    if is_err(saved):
                        logger.warning(
                            "Could not save review for work %s: %s",
                            task.id,
                            saved.error,
                        )
                    else:
                        task = saved.value
        text = (
            (task.review or task.result) if task.status == "completed" else task.summary
        )
        await self._send(task, text, attachments=attachments)

    async def _send(
        self,
        task: CharacterWork,
        text: str,
        *,
        attachments: tuple[WorkAttachment, ...] = (),
    ) -> None:
        await self._reporter.send(
            task,
            self._characters[task.character_id],
            text,
            attachments,
        )
