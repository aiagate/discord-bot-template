"""Tests for RequestJoinTeam use case failure scenarios."""

import pytest
from ulid import ULID

from app.core.result import is_err
from app.domain.repositories import IUnitOfWork
from app.usecases.memberships.request_join_team import (
    RequestJoinTeamCommand,
    RequestJoinTeamHandler,
)
from app.usecases.result import ErrorType


@pytest.mark.anyio
async def test_request_join_team_invalid_ids(uow: IUnitOfWork) -> None:
    """Test requesting to join team with invalid IDs."""
    handler = RequestJoinTeamHandler(uow)

    # Invalid Team ID
    res1 = await handler.handle(
        RequestJoinTeamCommand(team_id="invalid", user_id=str(ULID()))
    )
    assert is_err(res1)
    assert res1.error.type == ErrorType.VALIDATION_ERROR
    assert res1.error.message == "Invalid Team ID format"

    # Invalid User ID
    res2 = await handler.handle(
        RequestJoinTeamCommand(team_id=str(ULID()), user_id="invalid")
    )
    assert is_err(res2)
    assert res2.error.type == ErrorType.VALIDATION_ERROR
    assert res2.error.message == "Invalid User ID format"


@pytest.mark.anyio
async def test_request_join_team_not_found(uow: IUnitOfWork) -> None:
    """Test requesting to join non-existent team or user."""
    handler = RequestJoinTeamHandler(uow)
    valid_id = str(ULID())

    # Team not found
    res1 = await handler.handle(
        RequestJoinTeamCommand(team_id=valid_id, user_id=valid_id)
    )
    assert is_err(res1)
    assert res1.error.type == ErrorType.NOT_FOUND
    assert res1.error.message == "Team not found"

    # User not found (mock team existence via creating one)
    from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler

    team_handler = CreateTeamHandler(uow)
    team_id = (await team_handler.handle(CreateTeamCommand(name="Team A"))).unwrap().id

    res2 = await handler.handle(
        RequestJoinTeamCommand(team_id=team_id, user_id=valid_id)
    )
    assert is_err(res2)
    assert res2.error.type == ErrorType.NOT_FOUND
    assert res2.error.message == "User not found"
