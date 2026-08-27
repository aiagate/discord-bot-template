"""Cog to handle automated responses to direct messages."""

import discord
from discord.ext import commands
from flow_med import Mediator
from flow_res import is_err

from app.presentation.bot.cogs.base_cog import BaseCog
from app.usecases.chat.save_discord_chat import SaveDiscordChatCommand


class DirectMessageResponseCog(BaseCog, name="DM Response"):
    """Cog to handle automated responses to direct messages."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for messages and respond to DMs directly."""
        if message.author == self.bot.user:
            return

        if not isinstance(message.channel, discord.DMChannel):
            return

        guild_id = "DM"
        channel_id = str(message.channel.id)

        save_result = await Mediator.send_async(
            SaveDiscordChatCommand(
                user_id=str(message.author.id),
                guild_id=guild_id,
                channel_id=channel_id,
                content=message.content,
            )
        )
        if is_err(save_result):
            await message.channel.send("メッセージの保存に失敗しました。")
            return
