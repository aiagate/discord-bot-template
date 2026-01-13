import asyncio
import logging
import os
import sys

from injector import Injector

from app import container
from app.core.mediator import Mediator
from app.infrastructure.database import init_db
from app.worker.producer import heartbeat_producer

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format="[ %(levelname)-8s] %(asctime)s | %(name)-16s %(funcName)-16s| %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)


async def main() -> None:
    logger.info("Starting Worker Process")

    # 1. Initialize Dependencies (DB, etc.)
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL is not set")
        sys.exit(1)

    init_db(db_url, echo=True)

    # 2. Setup DI Container
    injector = Injector([container.configure])
    Mediator.initialize(injector)

    # Initialize AI Agent (if needed for context)
    # Note: If consumer uses AI service, we need it initialized.
    from app.domain.interfaces.ai_service import IAIService

    ai_service = injector.get(IAIService)
    await ai_service.initialize_ai_agent()

    # 3. Get EventBus
    from app.domain.interfaces.event_bus import IEventBus
    from app.worker.consumer import run_worker_consumer

    bus = injector.get(IEventBus)

    # 4. Start Background Tasks
    async with asyncio.TaskGroup() as tg:
        tg.create_task(heartbeat_producer(bus, interval_seconds=10))
        tg.create_task(run_worker_consumer(injector))


if __name__ == "__main__":
    try:
        from dotenv import load_dotenv

        load_dotenv(".env.local")
        load_dotenv()

        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Worker Process stopped")
