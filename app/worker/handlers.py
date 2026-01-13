import logging
import random

from injector import inject

from app.core.mediator import Mediator
from app.core.result import is_ok
from app.domain.interfaces.event_bus import Event, IEventBus
from app.usecases.chat.spontaneous_dialog import SpontaneousDialogCommand

logger = logging.getLogger(__name__)


class HeartbeatHandler:
    """Handles system.heartbeat events."""

    @inject
    def __init__(self, bus: IEventBus) -> None:
        self.bus = bus

    async def handle(self, event: Event) -> None:
        """Process heartbeat event."""
        # 30% chance to trigger spontaneous dialog
        if random.random() > 0.3:
            logger.debug("Heartbeat: Skipped spontaneous dialog (random)")
            return

        logger.info("Heartbeat: Triggering spontaneous dialog")

        result = await Mediator.send_async(SpontaneousDialogCommand())

        if is_ok(result):
            content, channel_id = result.unwrap()
            logger.info(f"Generated spontaneous content for channel {channel_id}")

            # Publish event for Bot to serve
            await self.bus.publish(
                "bot.speak", {"content": content, "channel_id": channel_id}
            )
        else:
            logger.error(f"Spontaneous dialog failed: {result.error}")
