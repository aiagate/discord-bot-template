# pyright: reportUnknownLambdaType=false

"""Discord cog for user management commands."""

from discord.ext import commands
from flow_med import Mediator

from app.bot.cogs.base_cog import BaseCog
from app.usecases.users.create_user import CreateUserCommand
from app.usecases.users.get_user import GetUserQuery


class UsersCog(BaseCog, name="Users"):
    """Discord commands for user management."""

    @commands.hybrid_group(name="users")
    async def users(self, ctx: commands.Context[commands.Bot]) -> None:
        """User management commands."""
        if ctx.invoked_subcommand is None:
            if ctx.command:
                await ctx.send_help(ctx.command)

    @users.command(name="get")
    async def users_get(
        self,
        ctx: commands.Context[commands.Bot],
        id: str,
    ) -> None:
        """Get user by ID. Usage: !users get <user_id>"""
        query = GetUserQuery(user_id=id)

        message = await (
            Mediator.send_async(query)
            .map(
                lambda value: (
                    f"User Information:\n"
                    f"ID: {value.id}\n"
                    f"Display Name: {value.display_name}\n"
                    f"Email: {value.email}"
                )
            )
            .unwrap()
        )

        await ctx.send(content=message)

    @users.command(name="create")
    async def users_create(
        self,
        ctx: commands.Context[commands.Bot],
        display_name: str,
        email: str,
    ) -> None:
        """Create new user. Usage: !users create <name> <email>"""
        message = await (
            Mediator.send_async(
                CreateUserCommand(display_name=display_name, email=email)
            )
            .and_then(
                lambda result: Mediator.send_async(GetUserQuery(user_id=result.id))
            )
            .map(
                lambda value: (
                    f"User Created:\n"
                    f"ID: {value.id}\n"
                    f"Display Name: {value.display_name}\n"
                    f"Email: {value.email}"
                )
            )
            .unwrap()
        )

        await ctx.send(content=message)


async def setup(bot: commands.Bot) -> None:
    """Setup function for cog loading."""
    await bot.add_cog(UsersCog(bot))
