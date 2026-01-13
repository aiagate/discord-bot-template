import asyncio
import logging
import os
import random
from typing import Any

import asyncpg
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.events import EventType
from app.core.mediator import Mediator
from app.core.result import is_err
from app.usecases.chat.spontaneous_dialog import (
    SpontaneousDialogCommand,  # Import to ensure registration
)
from app.worker.repository import QueueRepository

logger = logging.getLogger(__name__)


async def event_consumer(session_factory: async_sessionmaker[AsyncSession]) -> None:
    """Consumes events from the DB queue using LISTEN/NOTIFY."""
    logger.info("Event consumer started (LISTEN/NOTIFY mode)")

    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return

    # Convert sqlalchemy URL to asyncpg DSN if needed, usually they are compatible
    # but sqlalchemy might have +asyncpg driver. asyncpg.connect expects postgresql://...
    # simple fix replace postgresql+asyncpg -> postgresql
    dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    try:
        conn = await asyncpg.connect(dsn)

        # 1. Listen
        channel = "new_event_queue_item"

        # Event to wake up the loop
        notification_event = asyncio.Event()

        def listener(*args: Any) -> None:
            notification_event.set()

        await conn.add_listener(channel, listener)
        logger.info(f"Listening on channel: {channel}")

        try:
            while True:
                # 2. Process all pending items first (drain the queue)
                # We loop until queue is empty because one notification might mean multiple items
                # or we might have missed some while processing.
                while True:
                    processed = await _process_one_item(session_factory)
                    if not processed:
                        break

                # 3. Wait for notification or timeout
                notification_event.clear()
                try:
                    logger.debug("💤 Waiting for events...")
                    await asyncio.wait_for(notification_event.wait(), timeout=600)
                    logger.debug("⚡ Notification received!")
                except TimeoutError:
                    logger.debug("💓 Heartbeat check (Timeout)")
                    # In this architecture, Heartbeats are actual events in the table,
                    # so we don't necessarily need to do anything here unless we want internal self-check.
                    # The producer puts HEARTBEAT events in the table, which triggers notify, which wakes us up.
                    # So strictly speaking, this timeout is just a safety net.
                    pass

        finally:
            await conn.close()

    except asyncio.CancelledError:
        logger.info("Event consumer cancelled")
        raise
    except Exception as e:
        logger.error(f"Event consumer fatal error: {e}")
        await asyncio.sleep(5)


async def _process_one_item(session_factory: async_sessionmaker[AsyncSession]) -> bool:
    """Pop and process one item. Returns True if an item was processed."""
    async with session_factory() as session:
        repo = QueueRepository(session)
        item = await repo.dequeue_event()

        if not item:
            await session.commit()
            return False

        event_id, event = item
        logger.debug(f"Processing event: {event.type}")

        try:
            if event.type == EventType.HEARTBEAT:
                await _handle_heartbeat(repo)

            await repo.complete_event(event_id)
            await session.commit()
            return True

        except Exception as e:
            logger.error(f"Error processing event {event.type}: {e}")
            await repo.fail_event(event_id)
            await session.commit()
            return True  # We processed it (failed it), so we return True to continue draining


async def _handle_heartbeat(repo: QueueRepository) -> None:
    """Handle heartbeat event."""
    # 30% chance to trigger spontaneous dialog
    if random.random() > 0.3:
        logger.debug("Heartbeat: Skipped spontaneous dialog (random)")
        return

    logger.debug("Heartbeat: Triggering spontaneous dialog")

    command = SpontaneousDialogCommand()
    result_awaitable = Mediator.send_async(command)
    result = await result_awaitable

    if is_err(result):
        logger.error(f"Spontaneous dialog failed: {result.error}")
        return

    content, channel_id = result.unwrap()

    await repo.enqueue_command(
        command_type="SEND_DISCORD_MESSAGE",
        payload={"channel_id": channel_id, "content": content},
    )
    logger.info("Spontaneous dialog command enqueued")
