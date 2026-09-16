"""Team aggregate root."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects import TeamId, TeamName, Version


@dataclass(kw_only=True, slots=True)
class Team:
    """Team aggregate root.

    Implements IAuditable: timestamps are infrastructure concerns but exposed
    as read-only fields for auditing and display purposes. The repository layer
    automatically manages created_at and updated_at.

    Implements IVersionable: optimistic locking via version field, which is
    automatically managed by the repository layer during updates.
    """

    _id: TeamId = field(
        init=False,
        default_factory=lambda: TeamId.generate().expect(
            "TeamId.generate should succeed"
        ),
    )
    _name: TeamName
    _version: Version = field(init=False, default_factory=lambda: Version(0))
    _created_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))
    _updated_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))

    def __eq__(self, other: object) -> bool:
        """Compare entity identity, independently of its current state."""
        if not isinstance(other, Team) or type(self) is not type(other):
            return NotImplemented
        return self.id == other.id

    @classmethod
    def form(cls, name: TeamName) -> Team:
        """Factory method to create a new Team."""
        return Team(_name=name)

    @classmethod
    def restore(
        cls,
        *,
        team_id: TeamId,
        name: TeamName,
        version: Version,
        created_at: datetime,
        updated_at: datetime,
    ) -> Team:
        """Restore a team with persistence-managed identity and audit state."""
        team = cls(_name=name)
        team._id = team_id
        team._version = version
        team._created_at = created_at
        team._updated_at = updated_at
        return team

    @property
    def id(self) -> TeamId:
        return self._id

    @property
    def name(self) -> TeamName:
        return self._name

    @property
    def version(self) -> Version:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def change_name(self, new_name: TeamName) -> Team:
        """チーム名を変更するドメインロジック

        Note: updated_at is automatically managed by the repository layer.
        """
        self._name = new_name

        return self
