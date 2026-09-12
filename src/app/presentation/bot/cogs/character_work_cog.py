"""Discord controls and progress delivery for character work."""

import logging
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
from app.contracts.messages.times_message import TimesEpisodePlan, TimesWorkIntent
from app.contracts.ports.character_work import (
    ICharacterWorkContextProvider,
    ICharacterWorkExecutor,
    ICharacterWorkReporter,
    ICharacterWorkRequester,
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
WorkReviewer = Callable[
    [CharacterWork, CharacterDefinition, tuple[WorkAttachment, ...]],
    Awaitable[str | None],
]
TimesCompletionHandler = Callable[[CharacterWork], Awaitable[None]]
WorkFinishedHandler = Callable[[CharacterWork], Awaitable[None]]


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
        on_times_completion: TimesCompletionHandler | None = None,
        on_work_finished: WorkFinishedHandler | None = None,
        context_provider: ICharacterWorkContextProvider | None = None,
    ) -> None:
        super().__init__(bot, mediator)
        self._settings = settings
        self._executor = executor
        self._reporter = reporter
        self._reviewer = reviewer
        self._on_times_completion = on_times_completion
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
            on_finished=on_work_finished,
            context_provider=context_provider,
            allowed_guild_id=settings.guild_id,
            allowed_channel_ids=settings.channel_ids,
            allowed_user_ids=settings.user_ids,
        )

    async def cog_load(self) -> None:
        """Restore task links before accepting Discord messages."""
        await self._service.initialize()

    async def cog_unload(self) -> None:
        """Interrupt runtimes and persist their resumable identities."""
        await self._service.close()

    def set_times_completion_handler(
        self, handler: TimesCompletionHandler | None
    ) -> None:
        """Set the callback that turns a reviewed Times task into a follow-up."""
        self._on_times_completion = handler

    def set_work_finished_handler(self, handler: WorkFinishedHandler | None) -> None:
        """Set a callback run after a terminal task leaves the active slot."""
        self._service.set_finished_handler(handler)

    @property
    def requester(self) -> ICharacterWorkRequester:
        """Expose the service used by ordinary Gemini responses."""
        return self._service

    async def recover_times_completions(self) -> None:
        """Replay reviewed Times results after a process restart."""
        if self._on_times_completion is None:
            return
        for task in self._service.list_tasks():
            if task.status == "completed" and task.origin == "times" and task.review:
                try:
                    await self._on_times_completion(task)
                except Exception:
                    logger.exception(
                        "Could not recover Times follow-up for %s", task.id
                    )

    async def start_from_times(
        self, plan: TimesEpisodePlan, intent: TimesWorkIntent
    ) -> CharacterWork | None:
        """Start a work intent using the configured work webhook destination."""
        report_channel_id = min(self._settings.channel_ids, default="")
        result = await self._service.start_from_times(
            plan=plan,
            intent=intent,
            report_channel_id=report_channel_id,
        )
        if is_err(result):
            logger.warning("Could not start Times work: %s", result.error)
            return None
        return result.value

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
        if task.status not in {"completed", "failed", "stopped"}:
            return
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
        try:
            await self._send(task, text, attachments=attachments)
        finally:
            if (
                task.status == "completed"
                and task.origin == "times"
                and task.review
                and self._on_times_completion is not None
            ):
                try:
                    await self._on_times_completion(task)
                except Exception:
                    logger.exception(
                        "Could not publish Times follow-up for %s", task.id
                    )

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
