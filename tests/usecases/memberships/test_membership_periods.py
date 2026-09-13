"""Regression tests for membership enrollment periods."""

import pytest
from flow_res import is_err, is_ok

from app.contracts.ports import IUnitOfWork
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.repositories import RepositoryErrorType
from app.domain.value_objects import MembershipId
from app.usecases.memberships.join_team import JoinTeamCommand, JoinTeamHandler
from app.usecases.memberships.leave_team import LeaveTeamCommand, LeaveTeamHandler
from app.usecases.memberships.request_join_team import (
    RequestJoinTeamCommand,
    RequestJoinTeamHandler,
)
from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler
from app.usecases.users.create_user import CreateUserCommand, CreateUserHandler


async def _create_team_and_user(
    uow: IUnitOfWork,
) -> tuple[str, str]:
    """Create the two aggregates needed by membership use cases."""
    team_result = await CreateTeamHandler(uow).handle(
        CreateTeamCommand(name="Enrollment Team")
    )
    assert is_ok(team_result)

    user_result = await CreateUserHandler(uow).handle(
        CreateUserCommand(
            display_name="Enrollment User",
            email="enrollment@example.com",
        )
    )
    assert is_ok(user_result)
    return team_result.value.id, user_result.value.id


@pytest.mark.anyio
async def test_duplicate_immediate_join_returns_conflict(
    uow: IUnitOfWork,
) -> None:
    """A second active enrollment period is rejected as a conflict."""
    team_id, user_id = await _create_team_and_user(uow)
    handler = JoinTeamHandler(uow)

    first = await handler.handle(JoinTeamCommand(team_id, user_id))
    second = await handler.handle(JoinTeamCommand(team_id, user_id))

    assert is_ok(first)
    assert is_err(second)
    assert second.error.type is RepositoryErrorType.ALREADY_EXISTS


@pytest.mark.anyio
async def test_duplicate_join_request_returns_conflict(
    uow: IUnitOfWork,
) -> None:
    """A second pending enrollment period is rejected as a conflict."""
    team_id, user_id = await _create_team_and_user(uow)
    handler = RequestJoinTeamHandler(uow)

    first = await handler.handle(RequestJoinTeamCommand(team_id, user_id))
    second = await handler.handle(RequestJoinTeamCommand(team_id, user_id))

    assert is_ok(first)
    assert is_err(second)
    assert second.error.type is RepositoryErrorType.ALREADY_EXISTS


@pytest.mark.anyio
async def test_rejoin_creates_new_period_and_preserves_leaved_history(
    uow: IUnitOfWork,
) -> None:
    """Leaving permits a new period while retaining the old LEAVED row."""
    team_id, user_id = await _create_team_and_user(uow)
    join_handler = JoinTeamHandler(uow)
    first_result = await join_handler.handle(JoinTeamCommand(team_id, user_id))
    assert is_ok(first_result)

    leave_result = await LeaveTeamHandler(uow).handle(
        LeaveTeamCommand(first_result.value.id)
    )
    assert is_ok(leave_result)

    second_result = await join_handler.handle(JoinTeamCommand(team_id, user_id))
    assert is_ok(second_result)
    assert second_result.value.id != first_result.value.id

    async with uow:
        repository = uow.GetRepository(TeamMembership, MembershipId)
        first_loaded = await repository.get_by_id(
            MembershipId.from_primitive(first_result.value.id).expect("valid id")
        )
        second_loaded = await repository.get_by_id(
            MembershipId.from_primitive(second_result.value.id).expect("valid id")
        )

    assert is_ok(first_loaded)
    assert is_ok(second_loaded)
    assert first_loaded.value.status.value == "LEAVED"
    assert second_loaded.value.status.value == "ACTIVE"
