import asyncio
import logging

from app.core.events import AppEvent, EventType

logger = logging.getLogger(__name__)


async def heartbeat_producer(
    queue: asyncio.Queue[AppEvent], interval_seconds: int = 60
) -> None:
    """Produces heartbeat events at regular intervals."""
    logger.info(f"Heartbeat producer started (interval: {interval_seconds}s)")
    try:
        while True:
            await asyncio.sleep(interval_seconds)
            event = AppEvent(EventType.HEARTBEAT)
            await queue.put(event)
            logger.debug("Heartbeat event sent")
    except asyncio.CancelledError:
        logger.info("Heartbeat producer cancelled")
        raise
    except Exception as e:
        logger.error(f"Heartbeat producer error: {e}")
        # In a real app, might want to restart or handle gracefully
        raise
