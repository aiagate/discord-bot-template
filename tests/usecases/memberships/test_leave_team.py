"""Tests for LeaveTeam use case failure scenarios."""

import pytest
from flow_res import is_err
from ulid import ULID

from app.domain.repositories import IUnitOfWork
from app.usecases.memberships.join_team import JoinTeamCommand, JoinTeamHandler
from app.usecases.memberships.leave_team import (
    LeaveTeamCommand,
    LeaveTeamHandler,
)
from app.usecases.result import ErrorType
from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler
from app.usecases.users.create_user import CreateUserCommand, CreateUserHandler


@pytest.mark.anyio
async def test_leave_team_invalid_id(uow: IUnitOfWork) -> None:
    """Test leaving team with invalid membership ID."""
    handler = LeaveTeamHandler(uow)
    command = LeaveTeamCommand(membership_id="invalid-id")

    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert result.error.message == "Invalid Membership ID format"


@pytest.mark.anyio
async def test_leave_team_not_found(uow: IUnitOfWork) -> None:
    """Test leaving non-existent membership."""
    handler = LeaveTeamHandler(uow)
    command = LeaveTeamCommand(membership_id=str(ULID()))

    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.NOT_FOUND
    assert result.error.message == "Membership not found"


@pytest.mark.anyio
async def test_leave_team_already_left(uow: IUnitOfWork) -> None:
    """Test leaving a team that was already left."""
    # Setup
    team_handler = CreateTeamHandler(uow)
    team_id = (await team_handler.handle(CreateTeamCommand(name="Team A"))).unwrap().id

    user_handler = CreateUserHandler(uow)
    user_id = (
        (
            await user_handler.handle(
                CreateUserCommand(display_name="User A", email="user@example.com")
            )
        )
        .unwrap()
        .id
    )

    join_handler = JoinTeamHandler(uow)
    membership_id = (
        (await join_handler.handle(JoinTeamCommand(team_id=team_id, user_id=user_id)))
        .unwrap()
        .id
    )

    leave_handler = LeaveTeamHandler(uow)
    await leave_handler.handle(LeaveTeamCommand(membership_id=membership_id))

    # Execute again
    result = await leave_handler.handle(LeaveTeamCommand(membership_id=membership_id))

    # Assert
    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert result.error.message == "User has already leaved the team"
