"""Composition root for the application's request mediator."""

from typing import Any

from flow_med import HandlerRegistry, Mediator, Request, RequestHandler
from flow_res import AwaitableResult, Result
from injector import Injector

from app.usecases.chat.generate_character_response import (
    GenerateCharacterResponseHandler,
)
from app.usecases.chat.generate_times_episode import GenerateTimesEpisodeHandler
from app.usecases.chat.save_discord_chat import SaveDiscordChatHandler
from app.usecases.chat.save_line_chat import SaveLineChatHandler
from app.usecases.error_mapping import classify_error
from app.usecases.memberships.approve_join_request import (
    ApproveJoinRequestHandler,
)
from app.usecases.memberships.change_role import ChangeRoleHandler
from app.usecases.memberships.join_team import JoinTeamHandler
from app.usecases.memberships.leave_team import LeaveTeamHandler
from app.usecases.memberships.request_join_team import RequestJoinTeamHandler
from app.usecases.memory.consolidate_user_memory import (
    ConsolidateUserMemoryHandler,
)
from app.usecases.result import UseCaseError, UseCaseResultError
from app.usecases.teams.create_team import CreateTeamHandler
from app.usecases.teams.get_team import GetTeamHandler
from app.usecases.teams.update_team import UpdateTeamHandler
from app.usecases.users.create_user import CreateUserHandler
from app.usecases.users.get_user import GetUserHandler

_HANDLER_TYPES: tuple[type[RequestHandler[Any, Any]], ...] = (
    GenerateCharacterResponseHandler,
    GenerateTimesEpisodeHandler,
    SaveDiscordChatHandler,
    SaveLineChatHandler,
    ConsolidateUserMemoryHandler,
    ApproveJoinRequestHandler,
    ChangeRoleHandler,
    JoinTeamHandler,
    LeaveTeamHandler,
    RequestJoinTeamHandler,
    CreateTeamHandler,
    GetTeamHandler,
    UpdateTeamHandler,
    CreateUserHandler,
    GetUserHandler,
)


class ApplicationMediator:
    """Expose the mediator with the application's error boundary installed."""

    def __init__(self, mediator: Mediator) -> None:
        self._mediator = mediator

    def send_async[T](
        self,
        request: Request[Result[T, UseCaseResultError]],
    ) -> AwaitableResult[T, UseCaseError]:
        """Dispatch a request and return errors in the use case format."""
        return self._mediator.send_async(request).map_err(classify_error)


def create_application_mediator(injector: Injector) -> ApplicationMediator:
    """Create and configure the mediator for one application scope."""
    registry = HandlerRegistry()
    for handler_type in _HANDLER_TYPES:
        registry.handler(handler_type)

    return ApplicationMediator(Mediator(injector, registry))


__all__ = [
    "ApplicationMediator",
    "create_application_mediator",
]
