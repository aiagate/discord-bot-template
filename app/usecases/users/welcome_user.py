"""Welcome User background task."""

import logging
from dataclasses import dataclass

from flow_med import Request, RequestHandler
from flow_res import Ok, Result, is_err
from injector import inject

from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import UserId
from app.usecases.result import UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WelcomeUserCommand(Request[Result[None, UseCaseError]]):
    """Command to send welcome notification to user."""

    user_id: str


class WelcomeUserHandler(
    RequestHandler[WelcomeUserCommand, Result[None, UseCaseError]]
):
    """Handler for WelcomeUser background task."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(self, request: WelcomeUserCommand) -> Result[None, UseCaseError]:
        """Simulate sending a welcome notification."""
        user_id_result = UserId.from_primitive(request.user_id)
        if is_err(user_id_result):
            return Ok(None)  # Invalid ID, just ignore for background task

        user_id = user_id_result.unwrap()

        async with self._uow:
            user_repo = self._uow.GetRepository(User, UserId)
            user_result = await user_repo.get_by_id(user_id)

            if is_err(user_result):
                logger.error(f"User {request.user_id} not found for welcome task")
                return Ok(None)

            user = user_result.unwrap()

            # ここで実際のメール送信などの外部連携を行う
            logger.info(
                f"✨ [Background Task] Welcome, {user.display_name.to_primitive()}! (ID: {user.id.to_primitive()})"
            )

            return Ok(None)
