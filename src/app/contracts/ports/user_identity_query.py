"""Canonical user lookup by provider identity."""

from abc import ABC, abstractmethod

from flow_res import Result

from app.domain.repositories import RepositoryError
from app.domain.value_objects import ChatPlatform, UserId


class IUserIdentityQuery(ABC):
    """Resolve a provider participant without merging unknown identities."""

    @abstractmethod
    async def resolve(
        self,
        platform: ChatPlatform,
        external_participant_id: str,
    ) -> Result[UserId | None, RepositoryError]:
        """Return the mapped canonical User ID, or ``None`` when unmapped."""
        pass
