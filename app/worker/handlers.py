import logging

from injector import inject

from app.core.mediator import Mediator
from app.core.result import is_err
from app.domain.interfaces.event_bus import Event
from app.usecases.system.handle_heartbeat import HandleHeartbeatCommand

logger = logging.getLogger(__name__)


class HeartbeatHandler:
    """Handles system.heartbeat events."""

    @inject
    def __init__(self) -> None:
        pass

    async def handle(self, event: Event) -> None:
        """Process heartbeat event."""

        result = await Mediator.send_async(HandleHeartbeatCommand())

        if is_err(result):
            logger.error(f"Failed to handle heartbeat: {result.error}")
