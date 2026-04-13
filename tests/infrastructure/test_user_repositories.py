from flow_res import Err, Ok

"""Tests for User repository with version conflict handling."""

import pytest

from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork, RepositoryErrorType
from app.domain.value_objects import DisplayName, Email, UserId


@pytest.mark.anyio
async def test_user_repository_new_user_has_version_zero(
    uow: IUnitOfWork,
) -> None:
    """Test that newly created users start with version 0."""
    user = User.register(
        display_name=DisplayName.from_primitive("New User").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("newuser@example.com").expect(
            "Email.from_primitive should succeed"
        ),
    )

    async with uow:
        repo = uow.GetRepository(User)
        save_result = await repo.add(user)
        assert isinstance(save_result, Ok)
        saved_user = save_result.value
        assert saved_user.version.to_primitive() == 0
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # Verify by retrieving
    async with uow:
        repo = uow.GetRepository(User, UserId)
        get_result = await repo.get_by_id(saved_user.id)
        assert isinstance(get_result, Ok)
        retrieved_user = get_result.value
        assert retrieved_user.version.to_primitive() == 0


@pytest.mark.anyio
async def test_user_repository_version_increments_on_update(
    uow: IUnitOfWork,
) -> None:
    """Test that version increments correctly on each update."""
    user = User.register(
        display_name=DisplayName.from_primitive("Version User").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("version@example.com").expect(
            "Email.from_primitive should succeed"
        ),
    )

    # Initial save - version should be 0
    async with uow:
        repo = uow.GetRepository(User)
        save_result = await repo.add(user)
        assert isinstance(save_result, Ok)
        saved_user = save_result.value
        assert saved_user.version.to_primitive() == 0
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # First update - version should become 1
    async with uow:
        repo = uow.GetRepository(User, UserId)
        get_result = await repo.get_by_id(saved_user.id)
        assert isinstance(get_result, Ok)
        user_v0 = get_result.value
        assert user_v0.version.to_primitive() == 0

    user_v0_updated = user_v0.change_email(
        Email.from_primitive("version1@example.com").expect(
            "Email.from_primitive should succeed"
        )
    )

    async with uow:
        repo = uow.GetRepository(User)
        update_result = await repo.update(user_v0_updated)
        assert isinstance(update_result, Ok)
        user_v1 = update_result.value
        assert user_v1.version.to_primitive() == 1
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # Second update - version should become 2
    async with uow:
        repo = uow.GetRepository(User, UserId)
        get_result = await repo.get_by_id(user_v1.id)
        assert isinstance(get_result, Ok)
        user_v1_loaded = get_result.value
        assert user_v1_loaded.version.to_primitive() == 1

    user_v1_updated = user_v1_loaded.change_email(
        Email.from_primitive("version2@example.com").expect(
            "Email.from_primitive should succeed"
        )
    )

    async with uow:
        repo = uow.GetRepository(User)
        update_result = await repo.update(user_v1_updated)
        assert isinstance(update_result, Ok)
        user_v2 = update_result.value
        assert user_v2.version.to_primitive() == 2
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)


@pytest.mark.anyio
async def test_user_repository_concurrent_update_returns_version_conflict(
    uow: IUnitOfWork,
) -> None:
    """Test that concurrent updates to the same user return VERSION_CONFLICT."""
    # Create initial user
    user = User.register(
        display_name=DisplayName.from_primitive("Concurrent User").expect(
            "DisplayName.from_primitive should succeed"
        ),
        email=Email.from_primitive("concurrent@example.com").expect(
            "Email.from_primitive should succeed"
        ),
    )

    # Save user
    async with uow:
        repo = uow.GetRepository(User)
        save_result = await repo.add(user)
        assert isinstance(save_result, Ok)
        saved_user = save_result.value
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # Simulate two concurrent updates by loading user twice
    async with uow:
        repo = uow.GetRepository(User, UserId)
        user1_result = await repo.get_by_id(saved_user.id)
        assert isinstance(user1_result, Ok)
        user1 = user1_result.value

    async with uow:
        repo = uow.GetRepository(User, UserId)
        user2_result = await repo.get_by_id(saved_user.id)
        assert isinstance(user2_result, Ok)
        user2 = user2_result.value

    # Both have same version
    assert user1.version.to_primitive() == user2.version.to_primitive()

    # First update succeeds
    user1_updated = user1.change_email(
        Email.from_primitive("updated1@example.com").expect(
            "Email.from_primitive should succeed"
        )
    )
    async with uow:
        repo = uow.GetRepository(User)
        update1_result = await repo.update(user1_updated)
        assert isinstance(update1_result, Ok)
        updated_user1 = update1_result.value
        assert updated_user1.version.to_primitive() == 1  # Version incremented
        commit_result = await uow.commit()
        assert isinstance(commit_result, Ok)

    # Second update fails with VERSION_CONFLICT
    user2_updated = user2.change_email(
        Email.from_primitive("updated2@example.com").expect(
            "Email.from_primitive should succeed"
        )
    )
    async with uow:
        repo = uow.GetRepository(User)
        update2_result = await repo.update(user2_updated)
        assert isinstance(update2_result, Err)
        error = update2_result.error
        assert error.type == RepositoryErrorType.VERSION_CONFLICT
        assert "version" in error.message.lower()
        assert "concurrent" in error.message.lower()
