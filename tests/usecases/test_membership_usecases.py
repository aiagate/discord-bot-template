"""Integration tests for Membership use cases."""

import pytest
from flow_res import is_err, is_ok

from app.domain.repositories import IUnitOfWork
from app.usecases.memberships.approve_join_request import (
    ApproveJoinRequestCommand,
    ApproveJoinRequestHandler,
)
from app.usecases.memberships.change_role import ChangeRoleCommand, ChangeRoleHandler
from app.usecases.memberships.join_team import JoinTeamCommand, JoinTeamHandler
from app.usecases.memberships.leave_team import LeaveTeamCommand, LeaveTeamHandler
from app.usecases.memberships.request_join_team import (
    RequestJoinTeamCommand,
    RequestJoinTeamHandler,
)
from app.usecases.result import ErrorType
from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler
from app.usecases.users.create_user import CreateUserCommand, CreateUserHandler


@pytest.mark.anyio
async def test_join_team_success(uow: IUnitOfWork) -> None:
    """Test JoinTeamHandler successfully joins a user to a team."""
    # Setup: Create a team and a user
    team_handler = CreateTeamHandler(uow)
    team_result = await team_handler.handle(CreateTeamCommand(name="Team A"))
    assert is_ok(team_result)
    team_id = team_result.value.id

    user_handler = CreateUserHandler(uow)
    user_result = await user_handler.handle(
        CreateUserCommand(display_name="User A", email="user@example.com")
    )
    assert is_ok(user_result)
    user_id = user_result.value.id

    # Execute
    join_handler = JoinTeamHandler(uow)
    command = JoinTeamCommand(team_id=team_id, user_id=user_id)
    result = await join_handler.handle(command)

    # Assert
    assert is_ok(result)
    assert result.value.team_id == team_id
    assert result.value.user_id == user_id
    assert result.value.id


@pytest.mark.anyio
async def test_join_team_not_found(uow: IUnitOfWork) -> None:
    """Test JoinTeamHandler returns NOT_FOUND for missing team or user."""
    join_handler = JoinTeamHandler(uow)

    # Case 1: Team not found
    res1 = await join_handler.handle(
        JoinTeamCommand(team_id="invalid_team_id", user_id="some_user_id")
    )
    # Note: Validation fails first if format is totally wrong,
    # but "invalid_team_id" might pass ULID from_primitive if it looks like one,
    # or fail validation if it doesn't.
    # Our JoinTeamHandler checks is_err(team_id_result) which fails for "invalid_team_id"
    assert is_err(res1)
    assert res1.error.type == ErrorType.VALIDATION_ERROR

    # Use valid looking ULIDs but non-existent
    from ulid import ULID

    dummy_team_id = str(ULID())
    dummy_user_id = str(ULID())

    res2 = await join_handler.handle(
        JoinTeamCommand(team_id=dummy_team_id, user_id=dummy_user_id)
    )
    assert is_err(res2)
    assert res2.error.type == ErrorType.NOT_FOUND


@pytest.mark.anyio
async def test_request_join_team_success(uow: IUnitOfWork) -> None:
    """Test RequestJoinTeamHandler successfully creates a pending membership."""
    # Setup
    team_handler = CreateTeamHandler(uow)
    team_result = await team_handler.handle(CreateTeamCommand(name="Team B"))
    team_id = team_result.expect("Success").id

    user_handler = CreateUserHandler(uow)
    user_result = await user_handler.handle(
        CreateUserCommand(display_name="User B", email="userB@example.com")
    )
    user_id = user_result.expect("Success").id

    # Execute
    handler = RequestJoinTeamHandler(uow)
    command = RequestJoinTeamCommand(team_id=team_id, user_id=user_id)
    result = await handler.handle(command)

    # Assert
    assert is_ok(result)
    assert result.value.status == "PENDING"
    assert result.value.team_id == team_id


@pytest.mark.anyio
async def test_approve_join_request_success(uow: IUnitOfWork) -> None:
    """Test ApproveJoinRequestHandler successfully activates a membership."""
    # Setup
    team_handler = CreateTeamHandler(uow)
    team_id = (
        (await team_handler.handle(CreateTeamCommand(name="Team C")))
        .expect("Success")
        .id
    )

    user_handler = CreateUserHandler(uow)
    user_id = (
        (
            await user_handler.handle(
                CreateUserCommand(display_name="User C", email="userC@example.com")
            )
        )
        .expect("Success")
        .id
    )

    request_handler = RequestJoinTeamHandler(uow)
    membership_id = (
        (
            await request_handler.handle(
                RequestJoinTeamCommand(team_id=team_id, user_id=user_id)
            )
        )
        .expect("Success")
        .id
    )

    # Execute
    approve_handler = ApproveJoinRequestHandler(uow)
    result = await approve_handler.handle(
        ApproveJoinRequestCommand(membership_id=membership_id)
    )

    # Assert
    assert is_ok(result)
    assert result.value.status == "ACTIVE"


@pytest.mark.anyio
async def test_leave_team_success(uow: IUnitOfWork) -> None:
    """Test LeaveTeamHandler successfully sets status to LEAVED."""
    # Setup
    team_handler = CreateTeamHandler(uow)
    team_id = (
        (await team_handler.handle(CreateTeamCommand(name="Team D")))
        .expect("Success")
        .id
    )

    user_handler = CreateUserHandler(uow)
    user_id = (
        (
            await user_handler.handle(
                CreateUserCommand(display_name="User D", email="userD@example.com")
            )
        )
        .expect("Success")
        .id
    )

    join_handler = JoinTeamHandler(uow)
    membership_id = (
        (await join_handler.handle(JoinTeamCommand(team_id=team_id, user_id=user_id)))
        .expect("Success")
        .id
    )

    # Execute
    leave_handler = LeaveTeamHandler(uow)
    result = await leave_handler.handle(LeaveTeamCommand(membership_id=membership_id))

    # Assert
    assert is_ok(result)
    assert result.value.status == "LEAVED"


@pytest.mark.anyio
async def test_change_role_success(uow: IUnitOfWork) -> None:
    """Test ChangeRoleHandler successfully changes role."""
    # Setup
    team_handler = CreateTeamHandler(uow)
    team_id = (
        (await team_handler.handle(CreateTeamCommand(name="Team E")))
        .expect("Success")
        .id
    )

    user_handler = CreateUserHandler(uow)
    user_id = (
        (
            await user_handler.handle(
                CreateUserCommand(display_name="User E", email="userE@example.com")
            )
        )
        .expect("Success")
        .id
    )

    join_handler = JoinTeamHandler(uow)
    membership_id = (
        (await join_handler.handle(JoinTeamCommand(team_id=team_id, user_id=user_id)))
        .expect("Success")
        .id
    )

    # Execute
    role_handler = ChangeRoleHandler(uow)
    result = await role_handler.handle(
        ChangeRoleCommand(membership_id=membership_id, new_role="ADMIN")
    )

    # Assert
    assert is_ok(result)
    assert result.value.role == "ADMIN"
