"""Get User use case."""

import logging
from dataclasses import dataclass

from flow_res import Ok, Result, is_err
from injector import inject

from app.core.mediator import Request, RequestHandler
from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import UserId
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GetUserResult:
    """Result object for GetUser query."""

    id: str
    display_name: str
    email: str


@dataclass(frozen=True)
class GetUserQuery(Request[Result[GetUserResult, UseCaseError]]):
    """Query to get user by ID."""

    user_id: str


class GetUserHandler(RequestHandler[GetUserQuery, Result[GetUserResult, UseCaseError]]):
    """Handler for GetUser query."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: GetUserQuery
    ) -> Result[GetUserResult, UseCaseError]:
        """Get user by ID, returning a flattened result."""
        user_id_result = UserId.from_primitive(request.user_id).map_err(
            lambda _: UseCaseError(
                type=ErrorType.VALIDATION_ERROR,
                message="Invalid User ID format.",
            )
        )
        if is_err(user_id_result):
            return user_id_result

        user_id = user_id_result.unwrap()

        async with self._uow:
            user_repo = self._uow.GetRepository(User, UserId)
            user_result = (await user_repo.get_by_id(user_id)).map_err(
                lambda e: UseCaseError(type=ErrorType.NOT_FOUND, message=e.message)
            )

            if is_err(user_result):
                return user_result

            user = user_result.unwrap()
            return Ok(
                GetUserResult(
                    id=user.id.to_primitive(),
                    display_name=user.display_name.to_primitive(),
                    email=user.email.to_primitive(),
                )
            )
