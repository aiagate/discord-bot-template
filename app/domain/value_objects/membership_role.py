"""Membership role value object."""

from __future__ import annotations

from enum import Enum

from app.core.result import Err, Ok, Result


class MembershipRole(str, Enum):
    """Roles for team members."""

    OWNER = "OWNER"
    ADMIN = "ADMIN"
    MEMBER = "MEMBER"

    @classmethod
    def from_primitive(cls, value: str) -> Result[MembershipRole, ValueError]:
        """Create MembershipRole from string."""
        try:
            normalized = value.strip()
            if not normalized:
                return Err(ValueError("Membership role cannot be empty."))
            return Ok(cls(normalized.upper()))
        except ValueError:
            return Err(ValueError(f"Invalid role: {value}"))
