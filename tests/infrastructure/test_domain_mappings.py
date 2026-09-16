"""Tests for explicit aggregate-to-persistence mappings."""

from datetime import UTC, datetime

from app.domain.aggregates.team import Team
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.aggregates.user import User
from app.domain.value_objects import (
    DisplayName,
    Email,
    MembershipId,
    MembershipRole,
    MembershipStatus,
    TeamId,
    TeamName,
    UserId,
    Version,
)
from app.infrastructure.mappings.team import team_from_orm, team_to_orm
from app.infrastructure.mappings.team_membership import (
    team_membership_from_orm,
    team_membership_to_orm,
)
from app.infrastructure.mappings.user import user_from_orm, user_to_orm


def test_user_mapping_restores_id_version_and_audit_state() -> None:
    """User restoration keeps persistence-managed fields intact."""
    created_at = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    updated_at = datetime(2026, 9, 5, 9, 1, tzinfo=UTC)
    user = User.restore(
        user_id=UserId.generate().expect("valid id"),
        display_name=DisplayName.from_primitive("Alice").expect("valid name"),
        email=Email.from_primitive("alice@example.com").expect("valid email"),
        version=Version(4),
        created_at=created_at,
        updated_at=updated_at,
    )

    restored = user_from_orm(user_to_orm(user))

    assert restored == user
    assert restored.display_name == user.display_name
    assert restored.email == user.email
    assert restored.version == Version(4)
    assert restored.created_at == created_at
    assert restored.updated_at == updated_at


def test_team_mapping_restores_id_version_and_audit_state() -> None:
    """Team restoration keeps persistence-managed fields intact."""
    created_at = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    updated_at = datetime(2026, 9, 5, 9, 1, tzinfo=UTC)
    team = Team.restore(
        team_id=TeamId.generate().expect("valid id"),
        name=TeamName.from_primitive("Alpha").expect("valid name"),
        version=Version(3),
        created_at=created_at,
        updated_at=updated_at,
    )

    restored = team_from_orm(team_to_orm(team))

    assert restored == team
    assert restored.name == team.name
    assert restored.version == Version(3)
    assert restored.created_at == created_at
    assert restored.updated_at == updated_at


def test_membership_mapping_restores_enrollment_period_state() -> None:
    """Membership mapping preserves status, role, version, and audit fields."""
    created_at = datetime(2026, 9, 5, 9, 0, tzinfo=UTC)
    updated_at = datetime(2026, 9, 5, 9, 1, tzinfo=UTC)
    membership = TeamMembership.restore(
        membership_id=MembershipId.generate().expect("valid id"),
        team_id=TeamId.generate().expect("valid id"),
        user_id=UserId.generate().expect("valid id"),
        role=MembershipRole.ADMIN,
        status=MembershipStatus.LEAVED,
        version=Version(2),
        created_at=created_at,
        updated_at=updated_at,
    )

    restored = team_membership_from_orm(team_membership_to_orm(membership))

    assert restored == membership
    assert restored.team_id == membership.team_id
    assert restored.user_id == membership.user_id
    assert restored.role == membership.role
    assert restored.status is MembershipStatus.LEAVED
    assert restored.version == Version(2)
    assert restored.created_at == created_at
    assert restored.updated_at == updated_at
