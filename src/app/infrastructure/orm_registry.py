"""ORM mapping registry initialization.

This module registers all domain-to-ORM mappings at application startup.
Import this module to ensure mappings are registered before using repositories.
"""

from app.domain.aggregates.team import Team
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.aggregates.user import User
from app.infrastructure.orm_mapping import register_orm_mapping
from app.infrastructure.orm_models.team_membership_orm import TeamMembershipORM
from app.infrastructure.orm_models.team_orm import TeamORM
from app.infrastructure.orm_models.user_orm import UserORM


def init_orm_mappings() -> None:
    """Initialize all ORM mappings.

    This function should be called once at application startup,
    before any repository operations.
    """
    register_orm_mapping(User, UserORM)
    register_orm_mapping(Team, TeamORM)
    register_orm_mapping(TeamMembership, TeamMembershipORM)
