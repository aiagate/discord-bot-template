"""Join Team use case."""

import logging
from dataclasses import dataclass

from flow_res import Err, Ok, Result
from injector import inject

from app.core.mediator import Request, RequestHandler
from app.domain.aggregates.team import Team
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import TeamId, UserId
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class JoinTeamResult:
    """Result of joining a team."""

    id: str
    team_id: str
    user_id: str


@dataclass(frozen=True)
class JoinTeamCommand(Request[Result[JoinTeamResult, UseCaseError]]):
    """Command to join a team immediately."""

    team_id: str
    user_id: str


class JoinTeamHandler(
    RequestHandler[JoinTeamCommand, Result[JoinTeamResult, UseCaseError]]
):
    """Handler for JoinTeam command."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: JoinTeamCommand
    ) -> Result[JoinTeamResult, UseCaseError]:
        """User joins a team immediately."""
        team_id_result = TeamId.from_primitive(request.team_id)
        user_id_result = UserId.from_primitive(request.user_id)

        if isinstance(team_id_result, Err):
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR, message="Invalid Team ID format"
                )
            )
        if isinstance(user_id_result, Err):
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR, message="Invalid User ID format"
                )
            )

        team_id = team_id_result.unwrap()
        user_id = user_id_result.unwrap()

        async with self._uow:
            team_repo = self._uow.GetRepository(Team, TeamId)
            user_repo = self._uow.GetRepository(User, UserId)
            membership_repo = self._uow.GetRepository(TeamMembership)

            # Check if team exists
            team_exists = await team_repo.get_by_id(team_id)
            if isinstance(team_exists, Err):
                return Err(
                    UseCaseError(type=ErrorType.NOT_FOUND, message="Team not found")
                )

            # Check if user exists
            user_exists = await user_repo.get_by_id(user_id)
            if isinstance(user_exists, Err):
                return Err(
                    UseCaseError(type=ErrorType.NOT_FOUND, message="User not found")
                )

            # Check if already a member (Optional logic for now, could be handled by unique constraints)
            # For simplicity, we create the aggregate and let repository handle conflicts if indexed
            membership = TeamMembership.join(team_id=team_id, user_id=user_id)

            add_result = await membership_repo.add(membership)
            if isinstance(add_result, Err):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED, message=add_result.error.message
                    )
                )

            commit_result = await self._uow.commit()
            if isinstance(commit_result, Err):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED, message=commit_result.error.message
                    )
                )

            return Ok(
                JoinTeamResult(
                    id=membership.id.to_primitive(),
                    team_id=membership.team_id.to_primitive(),
                    user_id=membership.user_id.to_primitive(),
                )
            )
