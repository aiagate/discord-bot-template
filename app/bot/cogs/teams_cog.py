"""Discord cog for team management commands."""

# pyright: reportUnknownLambdaType=false

from discord.ext import commands
from flow_med import Mediator

from app.bot.cogs.base_cog import BaseCog
from app.usecases.memberships.join_team import JoinTeamCommand
from app.usecases.memberships.request_join_team import RequestJoinTeamCommand
from app.usecases.teams.create_team import CreateTeamCommand
from app.usecases.teams.get_team import GetTeamQuery
from app.usecases.teams.update_team import UpdateTeamCommand


class TeamsCog(BaseCog, name="Teams"):
    """Discord commands for team management."""

    @commands.hybrid_group(name="teams")
    async def teams(self, ctx: commands.Context[commands.Bot]) -> None:
        """Team management commands."""
        if ctx.invoked_subcommand is None:
            if ctx.command:
                await ctx.send_help(ctx.command)

    @teams.command(name="get")
    async def teams_get(
        self,
        ctx: commands.Context[commands.Bot],
        id: str,
    ) -> None:
        """Get team by ID. Usage: !teams get <team_id>"""
        query = GetTeamQuery(id=id)

        message = await (
            Mediator.send_async(query)
            .map(  # type: ignore[arg-type, return-value]  # pyright: ignore[reportUnknownLambdaType]
                lambda value: (f"Team Information:\nID: {value.id}\nName: {value.name}")
            )
            .unwrap()
        )

        await ctx.send(content=message)

    @teams.command(name="create")
    async def teams_create(
        self,
        ctx: commands.Context[commands.Bot],
        name: str,
    ) -> None:
        """Create new team. Usage: !teams create <name>"""
        message = await (
            Mediator.send_async(CreateTeamCommand(name=name))
            .and_then(  # type: ignore[arg-type, return-value]
                lambda result: Mediator.send_async(GetTeamQuery(id=result.id))
            )
            .map(  # type: ignore[arg-type, return-value]
                lambda value: (f"Team Created:\nID: {value.id}\nName: {value.name}")
            )
            .unwrap()
        )

        await ctx.send(content=message)

    @teams.command(name="update")
    async def teams_update(
        self,
        ctx: commands.Context[commands.Bot],
        team_id: str,
        *,
        new_name: str,
    ) -> None:
        """Update team name. Usage: !teams update <team_id> <new_name>"""
        message = await (
            Mediator.send_async(UpdateTeamCommand(team_id=team_id, new_name=new_name))
            .and_then(  # type: ignore[arg-type, return-value]
                lambda result: Mediator.send_async(GetTeamQuery(id=result.id))
            )
            .map(  # type: ignore[arg-type, return-value]
                lambda value: (
                    f"Team Updated Successfully:\n"
                    f"ID: {value.id}\n"
                    f"Name: {value.name}\n"
                    f"Version: {value.version}"
                )
            )
            .unwrap()
        )

        await ctx.send(content=message)

    @teams.command(name="join")
    async def teams_join(
        self,
        ctx: commands.Context[commands.Bot],
        team_id: str,
        user_id: str,
    ) -> None:
        """Join a team immediately. Usage: !teams join <team_id> <user_id>"""
        message = await (
            Mediator.send_async(JoinTeamCommand(team_id=team_id, user_id=user_id))
            .map(
                lambda value: (
                    f"Joined Team Successfully:\n"
                    f"Membership ID: {value.id}\n"
                    f"Team ID: {value.team_id}\n"
                    f"User ID: {value.user_id}"
                )
            )
            .unwrap()
        )
        await ctx.send(content=message)

    @teams.command(name="request")
    async def teams_request(
        self,
        ctx: commands.Context[commands.Bot],
        team_id: str,
        user_id: str,
    ) -> None:
        """Request to join a team. Usage: !teams request <team_id> <user_id>"""
        message = await (
            Mediator.send_async(
                RequestJoinTeamCommand(team_id=team_id, user_id=user_id)
            )
            .map(
                lambda value: (
                    f"Join Request Sent:\n"
                    f"Membership ID: {value.id}\n"
                    f"Team ID: {value.team_id}\n"
                    f"Status: {value.status}"
                )
            )
            .unwrap()
        )
        await ctx.send(content=message)


async def setup(bot: commands.Bot) -> None:
    """Setup function for cog loading."""
    await bot.add_cog(TeamsCog(bot))
