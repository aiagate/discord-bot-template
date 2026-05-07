"""Tests for Create User use case."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Err, is_err, is_ok

from app.domain.repositories import IUnitOfWork, RepositoryError, RepositoryErrorType
from app.usecases.result import ErrorType
from app.usecases.users.create_user import (
    CreateUserCommand,
    CreateUserHandler,
)


@pytest.mark.anyio
async def test_create_user_handler(uow: IUnitOfWork, event_bus: AsyncMock) -> None:
    """Test CreateUserHandler with real database."""
    handler = CreateUserHandler(uow, event_bus)

    command = CreateUserCommand(display_name="Alice", email="alice@example.com")
    result = await handler.handle(command)

    assert is_ok(result)
    user_id = result.value.id  # Now it's a str
    assert user_id  # ULID string should exist
    assert len(user_id) == 26  # ULID is 26 characters


@pytest.mark.anyio
async def test_create_user_handler_invalid_email(
    uow: IUnitOfWork, event_bus: AsyncMock
) -> None:
    """Test CreateUserHandler returns Err on invalid email format."""
    handler = CreateUserHandler(uow, event_bus)

    # Command with an invalid email format
    command = CreateUserCommand(display_name="Test User", email="invalid-email")
    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.VALIDATION_ERROR
    assert "Invalid email format" in result.error.message


@pytest.mark.anyio
async def test_create_user_handler_repository_error(event_bus: AsyncMock) -> None:
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

    handler = CreateUserHandler(mock_uow, event_bus)
    command = CreateUserCommand(display_name="Test User", email="test@example.com")
    result = await handler.handle(command)

    assert is_err(result)
    assert result.error.type == ErrorType.UNEXPECTED
    assert "Database connection failed" in result.error.message
