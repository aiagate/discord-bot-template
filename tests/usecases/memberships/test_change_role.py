"""Tests for ChangeRole use case failure scenarios."""

import pytest
from flow_res import is_err
from ulid import ULID

from app.contracts.ports import IUnitOfWork
from app.domain.repositories import RepositoryErrorType
from app.usecases.memberships.change_role import (
    ChangeRoleCommand,
    ChangeRoleHandler,
)
from app.usecases.memberships.join_team import JoinTeamCommand, JoinTeamHandler
from app.usecases.memberships.leave_team import LeaveTeamCommand, LeaveTeamHandler
from app.usecases.result import ErrorType
from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler
from app.usecases.users.create_user import CreateUserCommand, CreateUserHandler


@pytest.mark.anyio
async def test_change_role_invalid_id(uow: IUnitOfWork) -> None:
    """Test changing role with invalid membership ID."""
    handler = ChangeRoleHandler(uow)
    command = ChangeRoleCommand(membership_id="invalid-id", new_role="ADMIN")

    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert result.error.message == "Invalid Membership ID format"


@pytest.mark.anyio
async def test_change_role_invalid_role(uow: IUnitOfWork) -> None:
    """Test changing role with invalid role string."""
    handler = ChangeRoleHandler(uow)
    # Use a valid ULID so we fail at role validation first or second depending on checks
    # Implementation checks ID then Role.
    command = ChangeRoleCommand(membership_id=str(ULID()), new_role="SUPER_ADMIN")

    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert "Invalid Role" in result.error.message


@pytest.mark.anyio
async def test_change_role_not_found(uow: IUnitOfWork) -> None:
    """Test changing role for non-existent membership."""
    handler = ChangeRoleHandler(uow)
    command = ChangeRoleCommand(membership_id=str(ULID()), new_role="ADMIN")

    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == RepositoryErrorType.NOT_FOUND
    assert "not found" in result.error.message


@pytest.mark.anyio
async def test_change_role_after_leaving_returns_validation_error(
    uow: IUnitOfWork,
) -> None:
    """Test that a LEAVED membership cannot change role through the handler."""
    team_result = await CreateTeamHandler(uow).handle(
        CreateTeamCommand(name="Role Team")
    )
    team_id = team_result.unwrap().id

    user_result = await CreateUserHandler(uow).handle(
        CreateUserCommand(display_name="Role User", email="role@example.com")
    )
    user_id = user_result.unwrap().id

    membership_result = await JoinTeamHandler(uow).handle(
        JoinTeamCommand(team_id=team_id, user_id=user_id)
    )
    membership_id = membership_result.unwrap().id

    leave_result = await LeaveTeamHandler(uow).handle(
        LeaveTeamCommand(membership_id=membership_id)
    )
    assert not is_err(leave_result)

    result = await ChangeRoleHandler(uow).handle(
        ChangeRoleCommand(membership_id=membership_id, new_role="ADMIN")
    )

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert result.error.message == "Cannot change role for a LEAVED membership"
