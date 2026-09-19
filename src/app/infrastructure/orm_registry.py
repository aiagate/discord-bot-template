"""ORM mapping registry initialization.

This module registers all domain-to-ORM mappings at application startup.
Import this module to ensure mappings are registered before using repositories.
"""

from app.domain.aggregates.chat_message import ChatMessage
from app.domain.aggregates.team import Team
from app.domain.aggregates.team_membership import TeamMembership
from app.domain.aggregates.user import User
from app.infrastructure.mappings.chat_message import (
    chat_message_from_orm,
    chat_message_to_orm,
)
from app.infrastructure.mappings.team import team_from_orm, team_to_orm
from app.infrastructure.mappings.team_membership import (
    team_membership_from_orm,
    team_membership_to_orm,
)
from app.infrastructure.mappings.user import user_from_orm, user_to_orm
from app.infrastructure.orm_mapping import register_orm_mapping
from app.infrastructure.orm_models import (
    ChatMessageORM,
    TeamMembershipORM,
    TeamORM,
    UserORM,
)


def init_orm_mappings() -> None:
    """Initialize all ORM mappings.

    This function should be called once at application startup,
    before any repository operations.
    """
    register_orm_mapping(
        User,
        UserORM,
        to_orm=user_to_orm,
        from_orm=user_from_orm,
    )
    register_orm_mapping(
        Team,
        TeamORM,
        to_orm=team_to_orm,
        from_orm=team_from_orm,
    )
    register_orm_mapping(
        TeamMembership,
        TeamMembershipORM,
        to_orm=team_membership_to_orm,
        from_orm=team_membership_from_orm,
    )
    register_orm_mapping(
        ChatMessage,
        ChatMessageORM,
        to_orm=chat_message_to_orm,
        from_orm=chat_message_from_orm,
    )
