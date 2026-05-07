"""Tests for Welcome User background task."""

import pytest
from flow_res import is_ok

from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import DisplayName, Email, UserId
from app.usecases.users.welcome_user import WelcomeUserCommand, WelcomeUserHandler


@pytest.mark.anyio
async def test_welcome_user_handler_success(uow: IUnitOfWork) -> None:
    """Test WelcomeUserHandler successfully runs."""
    # Setup
    user = User.register(
        display_name=DisplayName.from_primitive("Test User").unwrap(),
        email=Email.from_primitive("test@example.com").unwrap(),
    )
    # Actually User.register creates a new ID. Let's just use it.

    async with uow:
        repo = uow.GetRepository(User, UserId)
        await repo.add(user)
        await uow.commit()

    handler = WelcomeUserHandler(uow)
    command = WelcomeUserCommand(user_id=user.id.to_primitive())
    result = await handler.handle(command)

    assert is_ok(result)


@pytest.mark.anyio
async def test_welcome_user_handler_invalid_id(uow: IUnitOfWork) -> None:
    """Test WelcomeUserHandler with invalid ID."""
    handler = WelcomeUserHandler(uow)
    command = WelcomeUserCommand(user_id="invalid")
    result = await handler.handle(command)

    assert is_ok(result)  # Should return Ok(None) and ignore


@pytest.mark.anyio
async def test_welcome_user_handler_not_found(uow: IUnitOfWork) -> None:
    """Test WelcomeUserHandler with non-existent ID."""
    from ulid import ULID

    handler = WelcomeUserHandler(uow)
    command = WelcomeUserCommand(user_id=str(ULID()))
    result = await handler.handle(command)

    assert is_ok(result)  # Should return Ok(None) and ignore
