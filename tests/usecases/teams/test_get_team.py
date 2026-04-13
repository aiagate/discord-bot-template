from flow_res import Err, Ok

"""Tests for Get Team use case."""

import pytest

from app.domain.aggregates.team import Team
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import TeamName
from app.usecases.result import ErrorType
from app.usecases.teams.get_team import GetTeamHandler, GetTeamQuery


@pytest.mark.anyio
async def test_get_team_handler(uow: IUnitOfWork) -> None:
    """Test GetTeamHandler retrieves existing team."""
    # First, create a team
    team = Team.form(
        name=TeamName.from_primitive("Alpha Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )

    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert isinstance(save_result, Ok)
        saved_team = save_result.value
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # Now test retrieving it
    handler = GetTeamHandler(uow)
    query = GetTeamQuery(id=saved_team.id.to_primitive())
    result = await handler.handle(query)

    assert isinstance(result, Ok)
    assert result.value.id == saved_team.id.to_primitive()
    assert result.value.name == "Alpha Team"


@pytest.mark.anyio
async def test_get_team_handler_not_found(uow: IUnitOfWork) -> None:
    """Test GetTeamHandler returns Err when team doesn't exist."""
    handler = GetTeamHandler(uow)

    # Use a valid ULID that doesn't exist in the database
    query = GetTeamQuery(id="01ARZ3NDEKTSV4RRFFQ69G5FAV")
    result = await handler.handle(query)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.NOT_FOUND
