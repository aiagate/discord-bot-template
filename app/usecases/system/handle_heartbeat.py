import random
from dataclasses import dataclass

from injector import inject

from app.core.mediator import Mediator, Request, RequestHandler
from app.core.result import Ok, Result, is_ok
from app.domain.interfaces.event_bus import IEventBus
from app.usecases.chat.spontaneous_dialog import SpontaneousDialogCommand
from app.usecases.result import UseCaseError


@dataclass
class HandleHeartbeatCommand(Request[Result[None, UseCaseError]]):
    """Command to handle system heartbeat."""

    pass


class HandleHeartbeatHandler(
    RequestHandler[HandleHeartbeatCommand, Result[None, UseCaseError]]
):
    """Handler for HandleHeartbeatCommand."""

    @inject
    def __init__(self, bus: IEventBus) -> None:
        self._bus = bus

    async def handle(
        self, request: HandleHeartbeatCommand
    ) -> Result[None, UseCaseError]:
        """Process heartbeat event."""
        # 30% chance to trigger spontaneous dialog
        if random.random() > 0.3:
            return Ok(None)

        # Trigger spontaneous dialog
        result = await Mediator.send_async(SpontaneousDialogCommand())

        if is_ok(result):
            content, channel_id = result.unwrap()
            # Publish event for Bot to serve
            await self._bus.publish(
                "bot.speak", {"content": content, "channel_id": channel_id}
            )

        return Ok(None)
