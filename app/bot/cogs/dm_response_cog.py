"""Cog to handle automated responses to direct messages."""

import discord
from discord.ext import commands

from app.bot.cogs.base_cog import BaseCog


class DirectMessageResponseCog(BaseCog, name="DM Response"):
    """Cog to handle automated responses to direct messages."""

    def __init__(self, bot: commands.Bot) -> None:
        super().__init__(bot)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        """Listen for messages and respond to DMs directly."""
        # Bot自身のメッセージには反応しない
        if message.author == self.bot.user:
            return

        # DMかどうかを判定して直接返信
        if isinstance(message.channel, discord.DMChannel):
            await message.channel.send(
                "DMを受け取りました！メッセージありがとうございます。"
            )
