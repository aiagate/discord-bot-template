"""Update Team use case."""

import logging
from dataclasses import dataclass

from injector import inject

from app.core.mediator import Request, RequestHandler
from app.core.result import Ok, Result, combine_all, is_err
from app.domain.aggregates.team import Team
from app.domain.repositories import IUnitOfWork, RepositoryError, RepositoryErrorType
from app.domain.value_objects import TeamId, TeamName
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


def _map_get_error(repo_error: RepositoryError, team_id: str) -> UseCaseError:
    """Map repository get errors to use case errors."""
    if repo_error.type == RepositoryErrorType.NOT_FOUND:
        return UseCaseError(
            type=ErrorType.NOT_FOUND,
            message=f"Team with id {team_id} not found",
        )
    return UseCaseError(type=ErrorType.UNEXPECTED, message=repo_error.message)


def _map_update_error(repo_error: RepositoryError, team_id: str) -> UseCaseError:
    """Map repository update errors to use case errors."""
    if repo_error.type == RepositoryErrorType.VERSION_CONFLICT:
        return UseCaseError(
            type=ErrorType.CONCURRENCY_CONFLICT,
            message=(
                f"Team with id {team_id} was modified by another user. "
                "Please reload and try again."
            ),
        )
    return UseCaseError(type=ErrorType.UNEXPECTED, message=repo_error.message)


@dataclass(frozen=True)
class UpdateTeamResult:
    id: str


@dataclass(frozen=True)
class UpdateTeamCommand(Request[Result[UpdateTeamResult, UseCaseError]]):
    """Command to update team name."""

    team_id: str
    new_name: str


class UpdateTeamHandler(
    RequestHandler[UpdateTeamCommand, Result[UpdateTeamResult, UseCaseError]]
):
    """Handler for UpdateTeam command."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: UpdateTeamCommand
    ) -> Result[UpdateTeamResult, UseCaseError]:
        """Update team name and return updated team info within a Result."""
        # Validate inputs
        team_id_result = TeamId.from_primitive(request.team_id)
        team_name_result = TeamName.from_primitive(request.new_name)

        combined_result = combine_all((team_id_result, team_name_result)).map_err(
            lambda e: UseCaseError(type=ErrorType.VALIDATION_ERROR, message=str(e))
        )
        if is_err(combined_result):
            return combined_result

        team_id, new_team_name = combined_result.unwrap()

        async with self._uow:
            team_repo = self._uow.GetRepository(Team, TeamId)

            # Get existing team
            get_result = (await team_repo.get_by_id(team_id)).map_err(
                lambda e: _map_get_error(e, request.team_id)
            )
            if is_err(get_result):
                return get_result

            team = get_result.unwrap()

            # Update team name
            team.change_name(new_team_name)

            # Save updated team (optimistic locking happens here)
            update_result = (await team_repo.update(team)).map_err(
                lambda e: _map_update_error(e, request.team_id)
            )
            if is_err(update_result):
                return update_result

            # Commit transaction
            commit_result = (await self._uow.commit()).map_err(
                lambda e: UseCaseError(type=ErrorType.UNEXPECTED, message=e.message)
            )

            if is_err(commit_result):
                return commit_result

            updated_team = update_result.unwrap()

            return Ok(UpdateTeamResult(id=updated_team.id.to_primitive()))
