"""Tests for Update Team use case."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, Ok

from app.domain.aggregates.team import Team
from app.domain.repositories import IUnitOfWork, RepositoryError, RepositoryErrorType
from app.domain.value_objects import TeamId, TeamName
from app.usecases.result import ErrorType
from app.usecases.teams.update_team import UpdateTeamCommand, UpdateTeamHandler


@pytest.mark.anyio
async def test_update_team_handler(uow: IUnitOfWork) -> None:
    """Test UpdateTeamHandler updates team name successfully."""
    # First, create a team
    team = Team.form(
        name=TeamName.from_primitive("Original Name").expect(
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

    # Now test updating it
    handler = UpdateTeamHandler(uow)
    command = UpdateTeamCommand(
        team_id=saved_team.id.to_primitive(), new_name="Updated Name"
    )
    result = await handler.handle(command)

    assert isinstance(result, Ok)
    team_id = result.value.id  # Now it's a str
    assert team_id == saved_team.id.to_primitive()
    # Version verification is no longer done here
    # (version is now part of TeamDTO via GetTeamQuery)


@pytest.mark.anyio
async def test_update_team_handler_not_found(uow: IUnitOfWork) -> None:
    """Test UpdateTeamHandler returns Err when team doesn't exist."""
    handler = UpdateTeamHandler(uow)

    # Use a valid ULID that doesn't exist in the database
    command = UpdateTeamCommand(
        team_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", new_name="New Name"
    )
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.NOT_FOUND


@pytest.mark.anyio
async def test_update_team_handler_validation_error(uow: IUnitOfWork) -> None:
    """Test UpdateTeamHandler returns validation error for invalid name."""
    # First, create a team
    team = Team.form(
        name=TeamName.from_primitive("Test Team").expect(
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

    # Try to update with empty name
    handler = UpdateTeamHandler(uow)
    command = UpdateTeamCommand(team_id=saved_team.id.to_primitive(), new_name="")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.VALIDATION_ERROR


@pytest.mark.anyio
async def test_update_team_handler_name_too_long(uow: IUnitOfWork) -> None:
    """Test UpdateTeamHandler returns validation error for name too long."""
    # First, create a team
    team = Team.form(
        name=TeamName.from_primitive("Test Team").expect(
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

    # Try to update with name that's too long
    handler = UpdateTeamHandler(uow)
    command = UpdateTeamCommand(
        team_id=saved_team.id.to_primitive(), new_name="x" * 101
    )
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.VALIDATION_ERROR


@pytest.mark.anyio
async def test_update_team_handler_concurrency_conflict(uow: IUnitOfWork) -> None:
    """Test UpdateTeamHandler returns concurrency conflict for stale data.

    This test verifies that when two users try to update the same team
    concurrently, the second update fails with a VERSION_CONFLICT error.
    """
    # Create a team
    team = Team.form(
        name=TeamName.from_primitive("Original Name").expect(
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

    # Simulate two users loading the team at the same time (both have version 0)
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        user1_team_result = await repo.get_by_id(saved_team.id)
        assert isinstance(user1_team_result, Ok)
        user1_team = user1_team_result.value

    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        user2_team_result = await repo.get_by_id(saved_team.id)
        assert isinstance(user2_team_result, Ok)
        user2_team = user2_team_result.value

    # Both users have version 0
    assert user1_team.version.to_primitive() == 0
    assert user2_team.version.to_primitive() == 0

    # First user updates successfully
    user1_team.change_name(
        TeamName.from_primitive("Updated by User 1").expect(
            "TeamName.from_primitive should succeed"
        )
    )
    async with uow:
        repo = uow.GetRepository(Team)
        update1_result = await repo.update(user1_team)
        assert isinstance(update1_result, Ok)
        assert update1_result.value.version.to_primitive() == 1
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # Second user tries to update with stale version (0) - should fail
    user2_team.change_name(
        TeamName.from_primitive("Updated by User 2").expect(
            "TeamName.from_primitive should succeed"
        )
    )
    async with uow:
        repo = uow.GetRepository(Team)
        update2_result = await repo.update(user2_team)
        assert isinstance(update2_result, Err)
        assert update2_result.error.type == RepositoryErrorType.VERSION_CONFLICT


@pytest.mark.anyio
async def test_update_team_handler_invalid_team_id(uow: IUnitOfWork) -> None:
    """Test UpdateTeamHandler returns validation error for invalid team_id."""
    handler = UpdateTeamHandler(uow)

    # Invalid ULID format
    command = UpdateTeamCommand(team_id="invalid-id", new_name="New Name")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.VALIDATION_ERROR


@pytest.mark.anyio
async def test_update_team_handler_get_unexpected_error() -> None:
    """Test UpdateTeamHandler returns unexpected error when get_by_id fails."""
    mock_uow = MagicMock(spec=IUnitOfWork)
    mock_repo = MagicMock()

    # Mock get_by_id to return an unexpected error
    mock_repo.get_by_id = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message="Database connection failed",
            )
        )
    )

    mock_uow.GetRepository.return_value = mock_repo
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    handler = UpdateTeamHandler(mock_uow)
    command = UpdateTeamCommand(
        team_id="01ARZ3NDEKTSV4RRFFQ69G5FAV", new_name="New Name"
    )
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.UNEXPECTED
    assert "Database connection failed" in result.error.message


@pytest.mark.anyio
async def test_update_team_handler_version_conflict_through_handler() -> None:
    """Test UpdateTeamHandler returns concurrency conflict when version conflicts."""
    mock_uow = MagicMock(spec=IUnitOfWork)
    mock_repo = MagicMock()

    # Create a mock team to return from get_by_id
    team_id = TeamId.generate().expect("TeamId.generate should succeed")
    team_name = TeamName.from_primitive("Original Name").expect(
        "TeamName.from_primitive should succeed"
    )
    mock_team = Team.form(name=team_name)

    # Mock get_by_id to return the team
    mock_repo.get_by_id = AsyncMock(return_value=Ok(mock_team))

    # Mock update to return a version conflict error
    mock_repo.update = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.VERSION_CONFLICT,
                message="Version conflict detected",
            )
        )
    )

    mock_uow.GetRepository.return_value = mock_repo
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    handler = UpdateTeamHandler(mock_uow)
    command = UpdateTeamCommand(team_id=team_id.to_primitive(), new_name="Updated Name")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.CONCURRENCY_CONFLICT
    assert "modified by another user" in result.error.message


@pytest.mark.anyio
async def test_update_team_handler_add_unexpected_error() -> None:
    """Test UpdateTeamHandler returns unexpected error when add fails."""
    mock_uow = MagicMock(spec=IUnitOfWork)
    mock_repo = MagicMock()

    # Create a mock team to return from get_by_id
    team_id = TeamId.generate().expect("TeamId.generate should succeed")
    team_name = TeamName.from_primitive("Original Name").expect(
        "TeamName.from_primitive should succeed"
    )
    mock_team = Team.form(name=team_name)

    # Mock get_by_id to return the team
    mock_repo.get_by_id = AsyncMock(return_value=Ok(mock_team))

    # Mock update to return an unexpected error
    mock_repo.update = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message="Database write failed",
            )
        )
    )

    mock_uow.GetRepository.return_value = mock_repo
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    handler = UpdateTeamHandler(mock_uow)
    command = UpdateTeamCommand(team_id=team_id.to_primitive(), new_name="Updated Name")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.UNEXPECTED
    assert "Database write failed" in result.error.message


@pytest.mark.anyio
async def test_update_team_handler_commit_failure() -> None:
    """Test UpdateTeamHandler returns unexpected error when commit fails."""
    mock_uow = MagicMock(spec=IUnitOfWork)
    mock_repo = MagicMock()

    # Create a mock team to return from get_by_id
    team_id = TeamId.generate().expect("TeamId.generate should succeed")
    team_name = TeamName.from_primitive("Original Name").expect(
        "TeamName.from_primitive should succeed"
    )
    mock_team = Team.form(name=team_name)

    # Mock get_by_id to return the team
    mock_repo.get_by_id = AsyncMock(return_value=Ok(mock_team))

    # Mock update to succeed
    updated_team = Team.form(
        name=TeamName.from_primitive("Updated Name").expect(
            "TeamName.from_primitive should succeed"
        ),
    )
    mock_repo.update = AsyncMock(return_value=Ok(updated_team))

    # Mock commit to fail
    mock_uow.commit = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.UNEXPECTED,
                message="Transaction commit failed",
            )
        )
    )

    mock_uow.GetRepository.return_value = mock_repo
    mock_uow.__aenter__ = AsyncMock(return_value=mock_uow)
    mock_uow.__aexit__ = AsyncMock(return_value=None)

    handler = UpdateTeamHandler(mock_uow)
    command = UpdateTeamCommand(team_id=team_id.to_primitive(), new_name="Updated Name")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.UNEXPECTED
    assert "Transaction commit failed" in result.error.message
