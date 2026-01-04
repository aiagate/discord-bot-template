"""Team membership aggregate root."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects import (
    MembershipId,
    MembershipRole,
    MembershipStatus,
    TeamId,
    UserId,
    Version,
)


@dataclass(kw_only=True, slots=True)
class TeamMembership:
    """Team membership aggregate root.

    Manages the relationship between a User and a Team, including roles and status.
    Implements IAuditable and IVersionable (managed by repository).
    """

    _id: MembershipId = field(
        init=False,
        default_factory=lambda: MembershipId.generate().expect(
            "MembershipId.generate should succeed"
        ),
    )
    _team_id: TeamId
    _user_id: UserId
    _role: MembershipRole
    _status: MembershipStatus
    _version: Version = field(init=False, default_factory=lambda: Version(0))
    _created_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))
    _updated_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))

    @classmethod
    def join(
        cls,
        team_id: TeamId,
        user_id: UserId,
    ) -> TeamMembership:
        """Factory method for a user joining a team."""
        return TeamMembership(
            _team_id=team_id,
            _user_id=user_id,
            _role=MembershipRole.MEMBER,
            _status=MembershipStatus.ACTIVE,
        )

    @classmethod
    def request_join(
        cls,
        team_id: TeamId,
        user_id: UserId,
    ) -> TeamMembership:
        """Factory method for a user requesting to join a team."""
        return TeamMembership(
            _team_id=team_id,
            _user_id=user_id,
            _role=MembershipRole.MEMBER,
            _status=MembershipStatus.PENDING,
        )

    @property
    def id(self) -> MembershipId:
        return self._id

    @property
    def team_id(self) -> TeamId:
        return self._team_id

    @property
    def user_id(self) -> UserId:
        return self._user_id

    @property
    def role(self) -> MembershipRole:
        return self._role

    @property
    def status(self) -> MembershipStatus:
        return self._status

    @property
    def version(self) -> Version:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def change_role(self, new_role: MembershipRole) -> TeamMembership:
        """Change the role of the member."""
        self._role = new_role
        return self

    def activate(self) -> TeamMembership:
        """Activate the membership (e.g. after approval)."""
        self._status = MembershipStatus.ACTIVE
        return self

    def leave(self) -> TeamMembership:
        """User leaves the team."""
        self._status = MembershipStatus.LEAVED
        return self
