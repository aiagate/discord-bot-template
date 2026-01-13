from unittest.mock import AsyncMock, patch

import pytest

from app.core.result import Ok, is_ok
from app.domain.interfaces.event_bus import IEventBus
from app.usecases.system.handle_heartbeat import (
    HandleHeartbeatCommand,
    HandleHeartbeatHandler,
)


@pytest.fixture
def mock_event_bus():
    return AsyncMock(spec=IEventBus)


@pytest.mark.asyncio
class TestHandleHeartbeatHandler:
    async def test_handle_heartbeat_skip_random(self, mock_event_bus: AsyncMock):
        handler = HandleHeartbeatHandler(mock_event_bus)

        # Mock random to return > 0.3 (should skip)
        with patch("random.random", return_value=0.4):
            result = await handler.handle(HandleHeartbeatCommand())

        assert is_ok(result)
        mock_event_bus.publish.assert_not_called()

    async def test_handle_heartbeat_trigger_success(self, mock_event_bus: AsyncMock):
        handler = HandleHeartbeatHandler(mock_event_bus)

        # Mock random (<= 0.3) and Mediator
        with (
            patch("random.random", return_value=0.2),
            patch(
                "app.core.mediator.Mediator.send_async", new_callable=AsyncMock
            ) as mock_send,
        ):
            # Setup Mediator success response
            mock_send.return_value = Ok(("Hello World", "123456"))

            result = await handler.handle(HandleHeartbeatCommand())

        assert is_ok(result)
        mock_send.assert_called_once()  # Should call SpontaneousDialogCommand
        mock_event_bus.publish.assert_called_once_with(
            "bot.speak", {"content": "Hello World", "channel_id": "123456"}
        )

    async def test_handle_heartbeat_trigger_failure(self, mock_event_bus: AsyncMock):
        handler = HandleHeartbeatHandler(mock_event_bus)

        # Mock random (<= 0.3) and Mediator
        with (
            patch("random.random", return_value=0.2),
            patch(
                "app.core.mediator.Mediator.send_async", new_callable=AsyncMock
            ) as mock_send,
        ):
            # Setup Mediator failure response (Err)
            # We need to simulate an error result from SpontaneousDialogCommand
            from app.core.result import Err
            from app.usecases.result import ErrorType, UseCaseError

            mock_send.return_value = Err(UseCaseError(ErrorType.UNEXPECTED, "Fail"))

            result = await handler.handle(HandleHeartbeatCommand())

        assert is_ok(result)  # Handler itself succeeds even if sub-command fails
        mock_event_bus.publish.assert_not_called()
