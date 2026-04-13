"""Change Role use case."""

import logging
from dataclasses import dataclass

from flow_res import Err, Ok, Result, is_err
from injector import inject

from app.core.mediator import Request, RequestHandler
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import MembershipId, MembershipRole
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ChangeRoleResult:
    """Result of changing a role."""

    id: str
    role: str


@dataclass(frozen=True)
class ChangeRoleCommand(Request[Result[ChangeRoleResult, UseCaseError]]):
    """Command to change a member's role."""

    membership_id: str
    new_role: str


class ChangeRoleHandler(
    RequestHandler[ChangeRoleCommand, Result[ChangeRoleResult, UseCaseError]]
):
    """Handler for ChangeRole command."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: ChangeRoleCommand
    ) -> Result[ChangeRoleResult, UseCaseError]:
        """Change a member's role."""
        membership_id_result = MembershipId.from_primitive(request.membership_id)
        new_role_result = MembershipRole.from_primitive(request.new_role)

        if is_err(membership_id_result):
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR,
                    message="Invalid Membership ID format",
                )
            )
        if is_err(new_role_result):
            return Err(
                UseCaseError(
                    type=ErrorType.VALIDATION_ERROR,
                    message=f"Invalid Role: {request.new_role}",
                )
            )

        membership_id = membership_id_result.unwrap()
        new_role = new_role_result.unwrap()

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

            membership.change_role(new_role)

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
                ChangeRoleResult(
                    id=membership.id.to_primitive(),
                    role=membership.role.value,
                )
            )
