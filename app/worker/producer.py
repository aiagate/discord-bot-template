import asyncio
import logging

from app.domain.interfaces.event_bus import IEventBus

logger = logging.getLogger(__name__)


async def heartbeat_producer(bus: IEventBus, interval_seconds: int = 60) -> None:
    """Produces heartbeat events at regular intervals."""
    logger.debug(f"Heartbeat producer started (interval: {interval_seconds}s)")
    try:
        while True:
            await asyncio.sleep(interval_seconds)

            await bus.publish("system.heartbeat", {})
            logger.debug("Heartbeat event published")

    except asyncio.CancelledError:
        logger.info("Heartbeat producer cancelled")
        raise
    except Exception as e:
        logger.error(f"Heartbeat producer error: {e}")
        await asyncio.sleep(5)
