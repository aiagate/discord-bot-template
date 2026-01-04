"""Discord cog for membership management commands."""

# pyright: reportUnknownLambdaType=false

from discord.ext import commands

from app.bot.cogs.base_cog import BaseCog
from app.mediator import Mediator
from app.usecases.memberships.approve_join_request import ApproveJoinRequestCommand
from app.usecases.memberships.change_role import ChangeRoleCommand
from app.usecases.memberships.leave_team import LeaveTeamCommand


class MembershipsCog(BaseCog, name="Memberships"):
    """Discord commands for membership management."""

    @commands.group(name="memberships")
    async def memberships(self, ctx: commands.Context[commands.Bot]) -> None:
        """Membership management commands."""
        if ctx.invoked_subcommand is None:
            if ctx.command:
                await ctx.send_help(ctx.command)

    @memberships.command(name="approve")
    async def memberships_approve(
        self,
        ctx: commands.Context[commands.Bot],
        membership_id: str,
    ) -> None:
        """Approve a join request. Usage: !memberships approve <membership_id>"""
        message = await (
            Mediator.send_async(ApproveJoinRequestCommand(membership_id=membership_id))
            .map(
                lambda value: (
                    f"Membership Approved:\nID: {value.id}\nStatus: {value.status}"
                )
            )
            .unwrap()
        )
        await ctx.send(content=message)

    @memberships.command(name="leave")
    async def memberships_leave(
        self,
        ctx: commands.Context[commands.Bot],
        membership_id: str,
    ) -> None:
        """Leave a team. Usage: !memberships leave <membership_id>"""
        message = await (
            Mediator.send_async(LeaveTeamCommand(membership_id=membership_id))
            .map(
                lambda value: (f"Leaved Team:\nID: {value.id}\nStatus: {value.status}")
            )
            .unwrap()
        )
        await ctx.send(content=message)

    @memberships.command(name="role")
    async def memberships_role(
        self,
        ctx: commands.Context[commands.Bot],
        membership_id: str,
        new_role: str,
    ) -> None:
        """Change member role. Usage: !memberships role <membership_id> <role>"""
        message = await (
            Mediator.send_async(
                ChangeRoleCommand(membership_id=membership_id, new_role=new_role)
            )
            .map(
                lambda value: (
                    f"Role Changed Successfully:\n"
                    f"ID: {value.id}\n"
                    f"New Role: {value.role}"
                )
            )
            .unwrap()
        )
        await ctx.send(content=message)


async def setup(bot: commands.Bot) -> None:
    """Setup function for cog loading."""
    await bot.add_cog(MembershipsCog(bot))
