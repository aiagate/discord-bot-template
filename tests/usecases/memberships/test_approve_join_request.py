from flow_res import Err

"""Tests for ApproveJoinRequest use case failure scenarios."""

import pytest
from ulid import ULID

from app.domain.repositories import IUnitOfWork
from app.usecases.memberships.approve_join_request import (
    ApproveJoinRequestCommand,
    ApproveJoinRequestHandler,
)
from app.usecases.memberships.join_team import JoinTeamCommand, JoinTeamHandler
from app.usecases.result import ErrorType
from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler
from app.usecases.users.create_user import CreateUserCommand, CreateUserHandler


@pytest.mark.anyio
async def test_approve_join_request_invalid_id(uow: IUnitOfWork) -> None:
    """Test approving with invalid membership ID."""
    handler = ApproveJoinRequestHandler(uow)
    command = ApproveJoinRequestCommand(membership_id="invalid-id")

    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert result.error.message == "Invalid Membership ID format"


@pytest.mark.anyio
async def test_approve_join_request_not_found(uow: IUnitOfWork) -> None:
    """Test approving non-existent membership."""
    handler = ApproveJoinRequestHandler(uow)
    command = ApproveJoinRequestCommand(membership_id=str(ULID()))

    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.NOT_FOUND
    assert result.error.message == "Membership not found"


@pytest.mark.anyio
async def test_approve_join_request_not_pending(uow: IUnitOfWork) -> None:
    """Test approving membership that is not in PENDING status."""
    # Setup: Create active membership
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
    # JoinTeam creates ACTIVE membership immediately
    membership_id = (
        (await join_handler.handle(JoinTeamCommand(team_id=team_id, user_id=user_id)))
        .unwrap()
        .id
    )

    # Execute
    handler = ApproveJoinRequestHandler(uow)
    command = ApproveJoinRequestCommand(membership_id=membership_id)
    result = await handler.handle(command)

    # Assert
    assert isinstance(result, Err)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert "Membership is not in PENDING status" in result.error.message
