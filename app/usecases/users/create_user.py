"""Create User use case."""

import logging
from dataclasses import dataclass

from flow_res import Ok, Result, combine_all, is_err
from injector import inject

from app.core.mediator import Request, RequestHandler
from app.domain.aggregates.user import User
from app.domain.repositories import IUnitOfWork
from app.domain.value_objects import DisplayName, Email
from app.usecases.result import ErrorType, UseCaseError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CreateUserResult:
    id: str


@dataclass(frozen=True)
class CreateUserCommand(Request[Result[CreateUserResult, UseCaseError]]):
    """Command to create new user."""

    display_name: str
    email: str


class CreateUserHandler(
    RequestHandler[CreateUserCommand, Result[CreateUserResult, UseCaseError]]
):
    """Handler for CreateUser command."""

    @inject
    def __init__(self, uow: IUnitOfWork) -> None:
        self._uow = uow

    async def handle(
        self, request: CreateUserCommand
    ) -> Result[CreateUserResult, UseCaseError]:
        """Create new user and return as DTO within a Result."""
        email_result = Email.from_primitive(request.email)
        display_name_result = DisplayName.from_primitive(request.display_name)

        combined_result = combine_all((email_result, display_name_result)).map_err(
            lambda e: UseCaseError(
                type=ErrorType.VALIDATION_ERROR,
                message=", ".join(str(exc) for exc in e.exceptions),
            )
        )
        if is_err(combined_result):
            return combined_result

        email, display_name = combined_result.unwrap()

        user = User.register(display_name=display_name, email=email)

        async with self._uow:
            user_repo = self._uow.GetRepository(User)
            add_result = (await user_repo.add(user)).map_err(
                lambda e: UseCaseError(type=ErrorType.UNEXPECTED, message=e.message)
            )

            if is_err(add_result):
                return add_result

            commit_result = (await self._uow.commit()).map_err(
                lambda e: UseCaseError(type=ErrorType.UNEXPECTED, message=e.message)
            )

            if is_err(commit_result):
                return commit_result

            id = user.id.to_primitive()
            return Ok(CreateUserResult(id=id))
