import logging

from injector import Injector

from app.domain.interfaces.event_bus import IEventBus
from app.worker.handlers import HeartbeatHandler

logger = logging.getLogger(__name__)


async def run_worker_consumer(injector: Injector) -> None:
    """Starts the Worker EventBus listener."""
    logger.info("Worker consumer starting...")

    bus = injector.get(IEventBus)

    # Register Handlers
    heartbeat_handler = injector.get(HeartbeatHandler)
    bus.subscribe("system.heartbeat", heartbeat_handler.handle)

    logger.info("Subscribed to: system.heartbeat")

    # Start the bus
    await bus.start()
