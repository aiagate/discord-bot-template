"""Tests for the Mediator."""

import pytest
from injector import Injector

from app import container
from app.core.mediator import HandlerNotFoundError, Mediator, Request, RequestHandler
from app.core.result import Ok, Result

# Initialize Mediator for tests
Mediator.initialize(Injector([container.configure]))


class MyQuery(Request[Result[str, Exception]]):
    pass


class MyQueryHandler(RequestHandler[MyQuery, Result[str, Exception]]):
    async def handle(self, request: MyQuery) -> Result[str, Exception]:
        return Ok("Handled")


class AnotherQuery(Request[Result[int, Exception]]):
    pass


@pytest.mark.anyio
async def test_mediator_send_registered_request() -> None:
    """Test that a request with an auto-registered handler can be sent."""
    # The MyQueryHandler should be auto-registered via the metaclass
    result = await Mediator.send_async(MyQuery()).unwrap()
    assert result == "Handled"


@pytest.mark.anyio
async def test_mediator_send_unregistered_raises_error() -> None:
    """Test that sending an unregistered request raises HandlerNotFoundError."""
    with pytest.raises(
        HandlerNotFoundError, match="Handler not found for request type"
    ):
        await Mediator.send_async(AnotherQuery())
