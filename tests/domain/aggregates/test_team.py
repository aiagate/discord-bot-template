"""Tests for Team aggregate."""

from datetime import UTC, datetime

from flow_res import is_err, is_ok

from app.domain.aggregates.team import Team
from app.domain.value_objects import TeamId, TeamName


def test_create_team_with_empty_name_returns_err() -> None:
    """Test that creating a Team with an empty name raises ValueError."""
    result = TeamName.from_primitive("")
    assert is_err(result)
    assert "Team name cannot be empty" in str(result.error)


def test_team_change_name() -> None:
    """Test that the change_name method updates the team's name."""
    team = Team.form(
        name=TeamName.from_primitive("Old Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )
    team.change_name(
        TeamName.from_primitive("New Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        )
    )
    assert team.name.to_primitive() == "New Team"


def test_team_creation_with_valid_data() -> None:
    """Test creating a team with valid data."""
    team_id_result = TeamId.generate()
    assert is_ok(team_id_result)

    team_name_result = TeamName.from_primitive("Alpha Team")
    assert is_ok(team_name_result)
    team_name = team_name_result.expect(
        "TeamName.from_primitive should succeed for valid name"
    )

    team = Team.form(
        name=team_name,
    )
    assert team.name == team_name
    assert isinstance(team.created_at, datetime)
    assert isinstance(team.updated_at, datetime)


def test_team_timestamps_use_utc() -> None:
    """Test that team timestamps use UTC timezone."""
    before = datetime.now(UTC)
    team = Team.form(
        name=TeamName.from_primitive("Test Team").expect(
            "TeamName.from_primitive should succeed for valid name"
        ),
    )
    after = datetime.now(UTC)

    assert before <= team.created_at <= after
    assert before <= team.updated_at <= after


def test_team_creation_with_invalid_name_returns_err() -> None:
    """Test that creating team with invalid name raises ValueError."""
    # Test name too long
    result_too_long = TeamName.from_primitive("x" * 101)
    assert is_err(result_too_long)
    assert "must not exceed 100 characters" in str(result_too_long.error)

    # Test name with leading/trailing whitespace
    result_whitespace = TeamName.from_primitive("  Team Name  ")
    assert is_err(result_whitespace)
    assert "cannot have leading or trailing whitespace" in str(result_whitespace.error)
