"""Tests for TeamMembership aggregate."""

from datetime import UTC, datetime

from app.domain.aggregates.team_membership import TeamMembership
from app.domain.value_objects import (
    MembershipRole,
    MembershipStatus,
    TeamId,
    UserId,
)


def test_team_membership_join() -> None:
    """Test creating a membership via join factory."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")

    membership = TeamMembership.join(team_id=team_id, user_id=user_id)

    assert membership.team_id == team_id
    assert membership.user_id == user_id
    assert membership.role == MembershipRole.MEMBER
    assert membership.status == MembershipStatus.ACTIVE
    assert isinstance(membership.created_at, datetime)
    assert membership.version.to_primitive() == 0


def test_team_membership_request_join() -> None:
    """Test creating a membership via request_join factory."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")

    membership = TeamMembership.request_join(team_id=team_id, user_id=user_id)

    assert membership.team_id == team_id
    assert membership.user_id == user_id
    assert membership.role == MembershipRole.MEMBER
    assert membership.status == MembershipStatus.PENDING


def test_team_membership_change_role() -> None:
    """Test changing the role of a member."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)

    membership.change_role(MembershipRole.ADMIN)

    assert membership.role == MembershipRole.ADMIN


def test_team_membership_activate() -> None:
    """Test activating a pending membership."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.request_join(team_id=team_id, user_id=user_id)

    membership.activate()

    assert membership.status == MembershipStatus.ACTIVE


def test_team_membership_leave() -> None:
    """Test user leaving the team."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)

    membership.leave()

    assert membership.status == MembershipStatus.LEAVED


def test_team_membership_timestamps_use_utc() -> None:
    """Test that membership timestamps use UTC timezone."""
    before = datetime.now(UTC)
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)
    after = datetime.now(UTC)

    assert before <= membership.created_at <= after
    assert before <= membership.updated_at <= after
