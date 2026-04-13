"""Tests for Create Team use case."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, is_err, is_ok

from app.domain.repositories import IUnitOfWork, RepositoryError, RepositoryErrorType
from app.usecases.result import ErrorType
from app.usecases.teams.create_team import CreateTeamCommand, CreateTeamHandler


@pytest.mark.anyio
async def test_create_team_handler(uow: IUnitOfWork) -> None:
    """Test CreateTeamHandler with real database."""
    handler = CreateTeamHandler(uow)

    command = CreateTeamCommand(name="Alpha Team")
    result = await handler.handle(command)

    assert is_ok(result)
    team_id = result.value.id  # Now it's a str
    assert team_id  # ULID string should exist
    assert len(team_id) == 26  # ULID is 26 characters


@pytest.mark.anyio
async def test_create_team_handler_validation_error(uow: IUnitOfWork) -> None:
    """Test CreateTeamHandler returns Err on validation error."""
    handler = CreateTeamHandler(uow)

    # Command with an empty name, which should fail domain validation
    command = CreateTeamCommand(name="")
    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR


@pytest.mark.anyio
async def test_create_team_handler_name_too_long(uow: IUnitOfWork) -> None:
    """Test CreateTeamHandler returns Err when team name is too long."""
    handler = CreateTeamHandler(uow)

    # Command with a name exceeding max length (100 characters)
    command = CreateTeamCommand(name="x" * 101)
    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert "must not exceed 100 characters" in result.error.message


@pytest.mark.anyio
async def test_create_team_handler_whitespace_validation(uow: IUnitOfWork) -> None:
    """Test CreateTeamHandler returns Err when team name has whitespace."""
    handler = CreateTeamHandler(uow)

    # Command with leading/trailing whitespace
    command = CreateTeamCommand(name="  Team Name  ")
    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert "leading or trailing whitespace" in result.error.message


@pytest.mark.anyio
async def test_create_team_handler_repository_error() -> None:
    """Test CreateTeamHandler returns Err when repository fails."""
    # Create a mock UnitOfWork that simulates repository error
    mock_uow = MagicMock(spec=IUnitOfWork)
    mock_repo = MagicMock()

    # Mock the repository to return an Err
    mock_repo.add = AsyncMock(
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

    handler = CreateTeamHandler(mock_uow)
    command = CreateTeamCommand(name="Test Team")
    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.UNEXPECTED
    assert "Database connection failed" in result.error.message
