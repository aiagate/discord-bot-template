"""Tests for Create User use case."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, Ok

from app.domain.repositories import IUnitOfWork, RepositoryError, RepositoryErrorType
from app.usecases.result import ErrorType
from app.usecases.users.create_user import (
    CreateUserCommand,
    CreateUserHandler,
)


@pytest.mark.anyio
async def test_create_user_handler(uow: IUnitOfWork) -> None:
    """Test CreateUserHandler with real database."""
    handler = CreateUserHandler(uow)

    command = CreateUserCommand(display_name="Alice", email="alice@example.com")
    result = await handler.handle(command)

    assert isinstance(result, Ok)
    user_id = result.value.id  # Now it's a str
    assert user_id  # ULID string should exist
    assert len(user_id) == 26  # ULID is 26 characters


@pytest.mark.anyio
async def test_create_user_handler_invalid_email(uow: IUnitOfWork) -> None:
    """Test CreateUserHandler returns Err on invalid email format."""
    handler = CreateUserHandler(uow)

    # Command with an invalid email format
    command = CreateUserCommand(display_name="Test User", email="invalid-email")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert "Invalid email format" in result.error.message


@pytest.mark.anyio
async def test_create_user_handler_repository_error() -> None:
    """Test CreateUserHandler returns Err when repository fails."""
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

    handler = CreateUserHandler(mock_uow)
    command = CreateUserCommand(display_name="Test User", email="test@example.com")
    result = await handler.handle(command)

    assert isinstance(result, Err)
    assert result.error.type == ErrorType.UNEXPECTED
    assert "Database connection failed" in result.error.message
