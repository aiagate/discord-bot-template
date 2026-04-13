"""Create Team use case."""

import logging
from dataclasses import dataclass

from flow_res import Err, Ok, Result, combine_all
from injector import inject

from app.core.mediator import Request, RequestHandler
from app.domain.aggregates.team import Team
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import TeamName
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateTeamResult:
    id: str


@dataclass(frozen=True)
class CreateTeamCommand(Request[Result[CreateTeamResult, UseCaseError]]):
    """Command to create new team."""

    name: str


class CreateTeamHandler(
    RequestHandler[CreateTeamCommand, Result[CreateTeamResult, UseCaseError]]
):
    """Handler for CreateTeam command."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: CreateTeamCommand
    ) -> Result[CreateTeamResult, UseCaseError]:
        """Create new team and return as DTO within a Result."""
        team_name_result = TeamName.from_primitive(request.name)

        combined_result = combine_all((team_name_result,)).map_err(
            lambda e: UseCaseError(
                type=ErrorType.VALIDATION_ERROR,
                message=", ".join(str(exc) for exc in e.exceptions),
            )
        )
        if isinstance(combined_result, Err):
            return combined_result

        (team_name,) = combined_result.unwrap()

        team = Team.form(name=team_name)

        async with self._uow:
            team_repo = self._uow.GetRepository(Team)
            add_result = (await team_repo.add(team)).map_err(
                lambda e: UseCaseError(type=ErrorType.UNEXPECTED, message=e.message)
            )

            if isinstance(add_result, Err):
                return add_result

            commit_result = (await self._uow.commit()).map_err(
                lambda e: UseCaseError(type=ErrorType.UNEXPECTED, message=e.message)
            )

            if isinstance(commit_result, Err):
                return commit_result

            id = team.id.to_primitive()
            return Ok(CreateTeamResult(id=id))
