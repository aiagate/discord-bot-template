"""Tests for TeamMembership aggregate."""

from datetime import UTC, datetime, timedelta

import pytest

from app.domain.aggregates.team_membership import (
    MembershipTransitionError,
    TeamMembership,
)
from app.domain.value_objects import (
    MembershipRole,
    MembershipStatus,
    TeamId,
    UserId,
    Version,
)
from tests.domain.aggregate_cases import AGGREGATE_CASES, aggregate_state


@pytest.mark.parametrize("status", list(MembershipStatus))
@pytest.mark.parametrize(
    ("operation", "expected_by_status"),
    [
        (
            "approve",
            {
                MembershipStatus.PENDING: MembershipStatus.ACTIVE,
                MembershipStatus.ACTIVE: None,
                MembershipStatus.LEAVED: None,
            },
        ),
        (
            "activate",
            {
                MembershipStatus.PENDING: MembershipStatus.ACTIVE,
                MembershipStatus.ACTIVE: None,
                MembershipStatus.LEAVED: None,
            },
        ),
        (
            "leave",
            {
                MembershipStatus.PENDING: MembershipStatus.LEAVED,
                MembershipStatus.ACTIVE: MembershipStatus.LEAVED,
                MembershipStatus.LEAVED: None,
            },
        ),
        (
            "change_role",
            {
                MembershipStatus.PENDING: MembershipStatus.PENDING,
                MembershipStatus.ACTIVE: MembershipStatus.ACTIVE,
                MembershipStatus.LEAVED: None,
            },
        ),
    ],
)
def test_membership_transition_table_preserves_state_on_rejection(
    status: MembershipStatus,
    operation: str,
    expected_by_status: dict[MembershipStatus, MembershipStatus | None],
) -> None:
    membership = TeamMembership.restore(
        **(AGGREGATE_CASES[TeamMembership].restore_values | {"status": status})
    )
    before = aggregate_state(membership)
    expected_status = expected_by_status[status]
    arguments = (MembershipRole.OWNER,) if operation == "change_role" else ()

    if expected_status is None:
        with pytest.raises(MembershipTransitionError):
            getattr(membership, operation)(*arguments)
        assert aggregate_state(membership) == before
    else:
        assert getattr(membership, operation)(*arguments) is membership
        changes: dict[str, object] = {"status": expected_status}
        if operation == "change_role":
            changes["role"] = MembershipRole.OWNER
        assert aggregate_state(membership) == before | changes


def test_membership_identity_survives_status_role_and_version_changes() -> None:
    """A changed period keeps its identity; reenrollment receives a new one."""
    membership = TeamMembership.request_join(
        TeamId.generate().expect("valid id"), UserId.generate().expect("valid id")
    )
    restored = TeamMembership.restore(
        membership_id=membership.id,
        team_id=membership.team_id,
        user_id=membership.user_id,
        role=MembershipRole.ADMIN,
        status=MembershipStatus.LEAVED,
        version=Version(2),
        created_at=membership.created_at,
        updated_at=membership.updated_at + timedelta(seconds=1),
    )

    assert membership is not restored
    assert membership == restored
    assert restored == membership
    assert membership != TeamMembership.request_join(
        membership.team_id, membership.user_id
    )
    assert membership != object()


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


def test_team_membership_change_role_pending() -> None:
    """Test changing the role of a pending member."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.request_join(team_id=team_id, user_id=user_id)

    membership.change_role(MembershipRole.ADMIN)

    assert membership.role == MembershipRole.ADMIN


def test_team_membership_cannot_change_role_after_leaving() -> None:
    """A LEAVED membership cannot change its role."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)
    membership.leave()

    with pytest.raises(
        MembershipTransitionError,
        match="LEAVED",
    ):
        membership.change_role(MembershipRole.ADMIN)

    assert membership.role == MembershipRole.MEMBER


def test_team_membership_activate() -> None:
    """Test activating a pending membership."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.request_join(team_id=team_id, user_id=user_id)

    membership.activate()

    assert membership.status == MembershipStatus.ACTIVE


def test_team_membership_cannot_approve_active_period() -> None:
    """Approval is a domain transition available only from PENDING."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)

    with pytest.raises(ValueError, match="PENDING"):
        membership.approve()


def test_team_membership_leave() -> None:
    """Test user leaving the team."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)

    membership.leave()

    assert membership.status == MembershipStatus.LEAVED


def test_team_membership_leave_pending() -> None:
    """A pending membership can transition to LEAVED."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.request_join(team_id=team_id, user_id=user_id)

    membership.leave()

    assert membership.status == MembershipStatus.LEAVED


def test_team_membership_cannot_leave_twice() -> None:
    """A LEAVED membership cannot be transitioned again."""
    team_id = TeamId.generate().expect("Success")
    user_id = UserId.generate().expect("Success")
    membership = TeamMembership.join(team_id=team_id, user_id=user_id)
    membership.leave()

    with pytest.raises(
        MembershipTransitionError,
        match="LEAVED",
    ):
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
