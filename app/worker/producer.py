import asyncio
import logging

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import AppEvent, EventType
from app.worker.repository import QueueRepository

logger = logging.getLogger(__name__)


async def heartbeat_producer(
    session_factory: async_sessionmaker[AsyncSession], interval_seconds: int = 60
) -> None:
    """Produces heartbeat events at regular intervals."""
    logger.debug(f"Heartbeat producer started (interval: {interval_seconds}s)")
    try:
        while True:
            await asyncio.sleep(interval_seconds)

            async with session_factory() as session:
                repo = QueueRepository(session)
                event = AppEvent(EventType.HEARTBEAT)
                await repo.enqueue_event(event)
                await session.commit()

            logger.debug("Heartbeat event sent to DB")
    except asyncio.CancelledError:
        logger.info("Heartbeat producer cancelled")
        raise
    except Exception as e:
        logger.error(f"Heartbeat producer error: {e}")
        # In a real app, might want to restart or handle gracefully
        # Wait a bit to avoid rapid loops on error
        await asyncio.sleep(5)
