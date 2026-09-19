"""Tests for the application mediator composition root."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_med import DuplicateHandlerError, InvalidHandlerError
from flow_res import Err, is_err, is_ok
from injector import Injector

from app import container
from app.application import mediator as mediator_module
from app.application.mediator import ApplicationMediator, create_application_mediator
from app.contracts.ports import IUnitOfWork
from app.domain.repositories import RepositoryError, RepositoryErrorType
from app.domain.value_objects import TeamId
from app.usecases.result import ErrorType
from app.usecases.teams.get_team import GetTeamQuery
from app.usecases.users.welcome_user import WelcomeUserCommand, WelcomeUserHandler


@pytest.mark.parametrize("same_type", [True, False])
def test_composition_rejects_duplicate_handlers(
    monkeypatch: pytest.MonkeyPatch, same_type: bool
) -> None:
    class OtherWelcomeHandler(WelcomeUserHandler):
        pass

    monkeypatch.setattr(
        mediator_module,
        "_HANDLER_TYPES",
        (WelcomeUserHandler, WelcomeUserHandler if same_type else OtherWelcomeHandler),
    )

    with pytest.raises(DuplicateHandlerError):
        create_application_mediator(Injector())


def test_composition_rejects_invalid_handler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mediator_module, "_HANDLER_TYPES", (object,))

    with pytest.raises(InvalidHandlerError):
        create_application_mediator(Injector())


def test_separate_application_scopes_can_register_the_same_handlers() -> None:
    assert create_application_mediator(Injector()) is not create_application_mediator(
        Injector()
    )


@pytest.mark.anyio
async def test_container_provides_dispatching_application_mediator(
    test_db_engine: None,
) -> None:
    """The composition root dispatches the welcome user handler."""
    injector = Injector([container.configure])
    mediator = injector.get(ApplicationMediator)

    result = await mediator.send_async(WelcomeUserCommand(user_id="invalid"))

    assert is_ok(result)
    assert result.value is None


@pytest.mark.anyio
async def test_mediator_maps_repository_error_at_application_boundary() -> None:
    """Repository errors are classified when they leave the application layer."""
    repository = MagicMock()
    repository.get_by_id = AsyncMock(
        return_value=Err(
            RepositoryError(
                type=RepositoryErrorType.VERSION_CONFLICT,
                message="stale database version",
            )
        )
    )
    uow = MagicMock(spec=IUnitOfWork)
    uow.GetRepository.return_value = repository
    uow.__aenter__ = AsyncMock(return_value=uow)
    uow.__aexit__ = AsyncMock(return_value=None)

    injector = Injector()
    injector.binder.bind(IUnitOfWork, to=uow)
    mediator = create_application_mediator(injector)

    result = await mediator.send_async(
        GetTeamQuery(id=TeamId.generate().expect("valid team id").to_primitive())
    )

    assert is_err(result)
    assert result.error.type is ErrorType.CONCURRENCY_CONFLICT
    assert result.error.message == "stale database version"
    assert result.error.display_message != "stale database version"
