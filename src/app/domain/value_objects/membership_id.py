"""MembershipId value object."""

from dataclasses import dataclass

from app.domain.value_objects.base_id import BaseId


@dataclass(frozen=True)
class MembershipId(BaseId):
    """MembershipId value object using ULID.

    Inherits all functionality from BaseId.
    """
