"""Tests for ChangeRole use case failure scenarios."""

import pytest
from flow_res import is_err
from ulid import ULID

from app.domain.repositories import IUnitOfWork
from app.usecases.memberships.change_role import (
    ChangeRoleCommand,
    ChangeRoleHandler,
)
from app.usecases.result import ErrorType


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
    assert result.error.type == ErrorType.NOT_FOUND
    assert result.error.message == "Membership not found"
