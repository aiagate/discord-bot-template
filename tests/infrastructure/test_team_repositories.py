"""Tests for Team repository components."""

import asyncio
from datetime import UTC, datetime

import pytest
from flow_res import is_err, is_ok

from app.domain.aggregates.team import Team
from app.domain.repositories import IUnitOfWork, RepositoryErrorType
from app.domain.value_objects import TeamId, TeamName


@pytest.mark.anyio
async def test_team_repository_save_and_get(uow: IUnitOfWork) -> None:
    """Test saving and retrieving a team."""
    team = Team.form(
        name=TeamName.from_primitive("Alpha Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )

    # Save team
    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert is_ok(save_result)
        saved_team = save_result.value
        assert saved_team.id == team.id
        assert saved_team.name.to_primitive() == "Alpha Team"
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # Retrieve team
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        get_result = await repo.get_by_id(saved_team.id)
        assert is_ok(get_result)
        retrieved_team = get_result.value
        assert retrieved_team.id == saved_team.id
        assert retrieved_team.name.to_primitive() == "Alpha Team"


@pytest.mark.anyio
async def test_team_repository_get_non_existent_raises_error(
    uow: IUnitOfWork,
) -> None:
    """Test that getting a non-existent team returns an Err."""
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        result = await repo.get_by_id(
            TeamId.from_primitive("01ARZ3NDEKTSV4RRFFQ69G5FAV").expect(
                "TeamId.from_primitive should succeed for valid ULID"
            )
        )
        assert is_err(result)


@pytest.mark.anyio
async def test_team_repository_delete(uow: IUnitOfWork) -> None:
    """Test deleting a team via the repository."""
    team = Team.form(
        name=TeamName.from_primitive("ToDelete Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )

    # 1. Create team
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        saved_team_result = await repo.add(team)
        assert is_ok(saved_team_result)
        saved_team = saved_team_result.value
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # 2. Delete team
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        delete_result = await repo.delete(saved_team)
        assert is_ok(delete_result)
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # 3. Verify team is deleted
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        get_result = await repo.get_by_id(saved_team.id)
        assert is_err(get_result)


@pytest.mark.anyio
async def test_team_repository_saves_timestamps(uow: IUnitOfWork) -> None:
    """Test that repository correctly saves and retrieves timestamps."""
    before_creation = datetime.now(UTC)

    team = Team.form(
        name=TeamName.from_primitive("Timestamp Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )

    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert is_ok(save_result)
        saved_team = save_result.value
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    after_creation = datetime.now(UTC)

    assert saved_team.created_at >= before_creation
    assert saved_team.created_at <= after_creation
    assert saved_team.updated_at >= before_creation
    assert saved_team.updated_at <= after_creation


@pytest.mark.anyio
async def test_team_repository_updates_timestamp_on_save(uow: IUnitOfWork) -> None:
    """Test that updated_at is automatically updated when saving existing team."""
    team = Team.form(
        name=TeamName.from_primitive("Update Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )

    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert is_ok(save_result)
        saved_team = save_result.value
        original_updated_at = saved_team.updated_at
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    await asyncio.sleep(0.01)

    saved_team.change_name(
        TeamName.from_primitive("Updated Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        )
    )

    async with uow:
        repo = uow.GetRepository(Team)
        update_result = await repo.update(saved_team)
        assert is_ok(update_result)
        updated_team = update_result.value
        commit_result = await uow.commit()
        assert is_ok(commit_result)
        # SQLite doesn't support microsecond precision well,
        # so we just check it's not exactly the same
        assert updated_team.updated_at != original_updated_at


@pytest.mark.anyio
async def test_team_repository_concurrent_update_returns_version_conflict(
    uow: IUnitOfWork,
) -> None:
    """Test that concurrent updates to the same team return VERSION_CONFLICT."""
    # Create initial team
    team = Team.form(
        name=TeamName.from_primitive("Concurrent Team").expect(
            "TeamName.from_primitive should succeed"
        ),
    )

    # Save team
    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert is_ok(save_result)
        saved_team = save_result.value
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # Simulate two concurrent updates by loading team twice
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        team1_result = await repo.get_by_id(saved_team.id)
        assert is_ok(team1_result)
        team1 = team1_result.value

    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        team2_result = await repo.get_by_id(saved_team.id)
        assert is_ok(team2_result)
        team2 = team2_result.value

    # Both have same version
    assert team1.version.to_primitive() == team2.version.to_primitive()

    # First update succeeds
    team1_updated = team1.change_name(
        TeamName.from_primitive("Updated by User 1").expect(
            "TeamName.from_primitive should succeed"
        )
    )
    async with uow:
        repo = uow.GetRepository(Team)
        update1_result = await repo.update(team1_updated)
        assert is_ok(update1_result)
        updated_team1 = update1_result.value
        assert updated_team1.version.to_primitive() == 1  # Version incremented
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # Second update fails with VERSION_CONFLICT
    team2_updated = team2.change_name(
        TeamName.from_primitive("Updated by User 2").expect(
            "TeamName.from_primitive should succeed"
        )
    )
    async with uow:
        repo = uow.GetRepository(Team)
        update2_result = await repo.update(team2_updated)
        assert is_err(update2_result)
        error = update2_result.error
        assert error.type == RepositoryErrorType.VERSION_CONFLICT
        assert "version" in error.message.lower()
        assert "concurrent" in error.message.lower()


@pytest.mark.anyio
async def test_team_repository_version_increments_on_update(
    uow: IUnitOfWork,
) -> None:
    """Test that version increments correctly on each update."""
    team = Team.form(
        name=TeamName.from_primitive("Version Team").expect(
            "TeamName.from_primitive should succeed"
        ),
    )

    # Initial save - version should be 0
    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert is_ok(save_result)
        saved_team = save_result.value
        assert saved_team.version.to_primitive() == 0
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # First update - version should become 1
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        get_result = await repo.get_by_id(saved_team.id)
        assert is_ok(get_result)
        team_v0 = get_result.value
        assert team_v0.version.to_primitive() == 0

    team_v0_updated = team_v0.change_name(
        TeamName.from_primitive("Updated Name 1").expect(
            "TeamName.from_primitive should succeed"
        )
    )

    async with uow:
        repo = uow.GetRepository(Team)
        update_result = await repo.update(team_v0_updated)
        assert is_ok(update_result)
        team_v1 = update_result.value
        assert team_v1.version.to_primitive() == 1
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # Second update - version should become 2
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        get_result = await repo.get_by_id(team_v1.id)
        assert is_ok(get_result)
        team_v1_loaded = get_result.value
        assert team_v1_loaded.version.to_primitive() == 1

    team_v1_updated = team_v1_loaded.change_name(
        TeamName.from_primitive("Updated Name 2").expect(
            "TeamName.from_primitive should succeed"
        )
    )

    async with uow:
        repo = uow.GetRepository(Team)
        update_result = await repo.update(team_v1_updated)
        assert is_ok(update_result)
        team_v2 = update_result.value
        assert team_v2.version.to_primitive() == 2
        commit_result = await uow.commit()
        assert is_ok(commit_result)


@pytest.mark.anyio
async def test_team_repository_new_team_has_version_zero(
    uow: IUnitOfWork,
) -> None:
    """Test that newly created teams start with version 0."""
    team = Team.form(
        name=TeamName.from_primitive("New Team").expect(
            "TeamName.from_primitive should succeed"
        ),
    )

    async with uow:
        repo = uow.GetRepository(Team)
        save_result = await repo.add(team)
        assert is_ok(save_result)
        saved_team = save_result.value
        assert saved_team.version.to_primitive() == 0
        commit_result = await uow.commit()
        assert is_ok(commit_result)

    # Verify by retrieving
    async with uow:
        repo = uow.GetRepository(Team, TeamId)
        get_result = await repo.get_by_id(saved_team.id)
        assert is_ok(get_result)
        retrieved_team = get_result.value
        assert retrieved_team.version.to_primitive() == 0
