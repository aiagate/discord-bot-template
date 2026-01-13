"""Leave Team use case."""

import logging
from dataclasses import dataclass

from injector import inject

from app.core.mediator import Request, RequestHandler
from app.core.result import Err, Ok, Result, is_err
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import MembershipId, MembershipStatus
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class LeaveTeamResult:
    """Result of leaving a team."""

    id: str
    status: str


@dataclass(frozen=True)
class LeaveTeamCommand(Request[Result[LeaveTeamResult, UseCaseError]]):
    """Command to leave a team."""

    membership_id: str


class LeaveTeamHandler(
    RequestHandler[LeaveTeamCommand, Result[LeaveTeamResult, UseCaseError]]
):
    """Handler for LeaveTeam command."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: LeaveTeamCommand
    ) -> Result[LeaveTeamResult, UseCaseError]:
        """User leaves a team."""
        membership_id_result = MembershipId.from_primitive(request.membership_id)

        if is_err(membership_id_result):
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR,
                    message="Invalid Membership ID format",
                )
            )

        membership_id = membership_id_result.unwrap()

        async with self._uow:
            membership_repo = self._uow.GetRepository(TeamMembership, MembershipId)

            membership_result = await membership_repo.get_by_id(membership_id)
            if is_err(membership_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.NOT_FOUND, message="Membership not found"
                    )
                )

            membership = membership_result.unwrap()

            if membership.status == MembershipStatus.LEAVED:
                return Err(
                    UseCaseError(
                        type=ErrorType.VALIDATION_ERROR,
                        message="User has already leaved the team",
                    )
                )

            membership.leave()

            update_result = await membership_repo.update(membership)
            if is_err(update_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED, message=update_result.error.message
                    )
                )

            commit_result = await self._uow.commit()
            if is_err(commit_result):
                return Err(
                    UseCaseError(
                        type=ErrorType.UNEXPECTED, message=commit_result.error.message
                    )
                )

            return Ok(
                LeaveTeamResult(
                    id=membership.id.to_primitive(),
                    status=membership.status.value,
                )
            )
