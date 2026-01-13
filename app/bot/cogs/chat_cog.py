# pyright: reportUnknownLambdaType=false

"""Discord cog for user management commands."""

from discord.ext import commands

from app.bot.cogs.base_cog import BaseCog
from app.mediator import Mediator
from app.usecases.chat.generate_content import GenerateContentQuery
from app.usecases.chat.generate_content_without_lean import (
    GenerateContentWithoutLeanQuery,
)


class ChatCog(BaseCog, name="Chat"):
    """Discord commands for agent chat."""

    @commands.group(name="chat")
    async def chat(self, ctx: commands.Context[commands.Bot]) -> None:
        """Chat commands."""
        if ctx.invoked_subcommand is None:
            if ctx.command:
                await ctx.send_help(ctx.command)

    @chat.command(name="lean")
    async def chat_lean(
        self,
        ctx: commands.Context[commands.Bot],
        *,
        message: str,
    ) -> None:
        """Responds with AI generated content. Usage: !chat lean <message>"""
        async with ctx.channel.typing():
            request = GenerateContentQuery(prompt=message)
            responce = (
                await Mediator.send_async(request).map(lambda value: value).unwrap()
            )

            await ctx.channel.send(responce)

    @chat.command(name="temp")
    async def chat_temp(
        self,
        ctx: commands.Context[commands.Bot],
        *,
        message: str,
    ) -> None:
        """Responds with AI generated content. Not learned AI agent. Usage: !chat temp <message>"""
        async with ctx.channel.typing():
            request = GenerateContentWithoutLeanQuery(prompt=message)
            responce = (
                await Mediator.send_async(request).map(lambda value: value).unwrap()
            )

            await ctx.channel.send(responce)


async def setup(bot: commands.Bot) -> None:
    """Setup function for cog loading."""
    await bot.add_cog(ChatCog(bot))
