"""Get Team use case."""

import logging
from dataclasses import dataclass

from injector import inject

from app.core.mediator import Request, RequestHandler
from app.core.result import Ok, Result, is_err
from app.domain.aggregates.team import Team
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import TeamId
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetTeamResult:
    """Result object for GetTeam query."""

    id: str
    name: str
    version: int


@dataclass(frozen=True)
class GetTeamQuery(Request[Result[GetTeamResult, UseCaseError]]):
    """Query to get team by ID."""

    id: str


class GetTeamHandler(RequestHandler[GetTeamQuery, Result[GetTeamResult, UseCaseError]]):
    """Handler for GetTeam query."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: GetTeamQuery
    ) -> Result[GetTeamResult, UseCaseError]:
        """Get team by ID, returning a flattened result."""
        team_id_result = TeamId.from_primitive(request.id).map_err(
            lambda _: UseCaseError(
                type=ErrorType.VALIDATION_ERROR,
                message="Invalid Team ID format.",
            )
        )
        if is_err(team_id_result):
            return team_id_result

        team_id = team_id_result.unwrap()

        async with self._uow:
            team_repo = self._uow.GetRepository(Team, TeamId)
            team_result = (await team_repo.get_by_id(team_id)).map_err(
                lambda e: UseCaseError(type=ErrorType.NOT_FOUND, message=e.message)
            )

            if is_err(team_result):
                return team_result

            team = team_result.unwrap()
            return Ok(
                GetTeamResult(
                    id=team.id.to_primitive(),
                    name=team.name.to_primitive(),
                    version=team.version.to_primitive(),
                )
            )
