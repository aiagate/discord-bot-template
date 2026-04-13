"""Tests for infrastructure Unit of Work component."""

import pytest
from flow_res import is_ok

from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import DisplayName, Email, UserId


@pytest.mark.anyio
async def test_uow_rollback(uow: IUnitOfWork) -> None:
    """Test that the Unit of Work rolls back transactions on error."""
    user = User.register(
        display_name=DisplayName.from_primitive("Rollback Test").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("rollback@example.com").expect(
            "Email.from_primitive should succeed for valid email"
        ),
    )
    initial_user = None

    # 1. Save a user and get its ID
    async with uow:
        repo = uow.GetRepository(User, UserId)
        save_result = await repo.add(user)
        assert is_ok(save_result)
        initial_user = save_result.value
        assert initial_user.id  # ULID should exist
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # 2. Attempt to update the user in a failing transaction
    try:
        async with uow:
            repo = uow.GetRepository(User, UserId)
            get_result = await repo.get_by_id(initial_user.id)
            assert is_ok(get_result)
            user_to_update = get_result.value
            user_to_update.change_email(
                Email.from_primitive("updated@example.com").expect(
                    "Email.from_primitive should succeed"
                )
            )
            await repo.update(user_to_update)
            raise ValueError("Simulating a failure")
    except ValueError:
        # Expected failure
        pass

    # 3. Verify that the email was NOT updated (rollback worked)
    async with uow:
        repo = uow.GetRepository(User, UserId)
        retrieved_result = await repo.get_by_id(initial_user.id)
        assert is_ok(retrieved_result)
        retrieved_user = retrieved_result.value
        assert retrieved_user.email.to_primitive() == "rollback@example.com"
