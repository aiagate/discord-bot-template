"""Membership status value object."""

from __future__ import annotations

from enum import Enum

from app.core.result import Err, Ok, Result


class MembershipStatus(str, Enum):
    """Status of team membership."""

    PENDING = "PENDING"
    ACTIVE = "ACTIVE"
    LEAVED = "LEAVED"

    @classmethod
    def from_primitive(cls, value: str) -> Result[MembershipStatus, ValueError]:
        """Create MembershipStatus from string."""
        try:
            return Ok(cls(value.upper()))
        except ValueError:
            return Err(ValueError(f"Invalid status: {value}"))
