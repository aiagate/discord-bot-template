import asyncio
import json
import logging
import os
from typing import Any

import asyncpg

from app.domain.interfaces.event_bus import Event, EventHandler, IEventBus

logger = logging.getLogger(__name__)


class PostgresEventBus(IEventBus):
    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._pool: asyncpg.Pool | None = None
        self._running = False

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            # This might happen during build/test if env not set, but generally needed.
            self.dsn = ""
        else:
            self.dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed to topic: {topic}")

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not self._pool:
            logger.warning("EventBus not started, cannot publish events.")
            return

        async with self._pool.acquire() as conn:
            try:
                # Insert into event_queue for persistence/history
                # Using event_queue table: type, payload, status
                row = await conn.fetchrow(
                    """
                    INSERT INTO event_queue (type, payload, status)
                    VALUES ($1, $2, 'PENDING')
                    RETURNING id
                    """,
                    topic,
                    json.dumps(payload),
                )

                # Notify listeners
                # We send minimal payload to avoid size limits on NOTIFY
                # The payload includes the topic and the ID of the inserted event
                notify_payload = json.dumps(
                    {
                        "topic": topic,
                        "id": str(row["id"]) if row else None,
                        "payload": payload,
                    }
                )

                await conn.execute(f"NOTIFY bot_events, '{notify_payload}'")
                logger.debug(f"Published event: {topic}")

            except Exception as e:
                logger.error(f"Failed to publish event {topic}: {e}")
                raise

    async def start(self) -> None:
        if not self.dsn:
            logger.error("DATABASE_URL not set, cannot start EventBus.")
            return

        self._running = True
        try:
            self._pool = await asyncpg.create_pool(self.dsn)
            logger.info("EventBus connection pool created.")

            # Create a dedicated connection for listening
            # The pool is used for publishing, but we need a persistent connection for LISTEN
            # We can acquire one from the pool or create a separate one.
            # Ideally separate to avoid blocking a pool slot forever.
            listener_conn = await asyncpg.connect(self.dsn)

            async def _listener(
                connection: Any, pid: int, channel: str, payload: str
            ) -> None:
                asyncio.create_task(self._process_notification(payload))

            await listener_conn.add_listener("bot_events", _listener)
            logger.info("🚀 Postgres Event Bus Started. Listening on 'bot_events'.")

            # Keep the listener alive
            while self._running:
                await asyncio.sleep(1)

        except Exception as e:
            logger.error(f"Error in EventBus start: {e}")
            raise
        finally:
            if self._pool:
                await self._pool.close()

    async def _process_notification(self, raw_payload: str) -> None:
        """Process incoming notifications and dispatch to handlers."""
        try:
            data = json.loads(raw_payload)
            topic = data.get("topic")
            payload = data.get("payload", {})

            if not topic:
                logger.warning("Received notification without topic.")
                return

            event = Event(topic=topic, payload=payload)

            if handlers := self._handlers.get(topic):
                for handler in handlers:
                    try:
                        await handler(event)
                    except Exception as e:
                        logger.error(f"Error in event handler for {topic}: {e}")
        except json.JSONDecodeError:
            logger.error(f"Failed to decode notification payload: {raw_payload}")
        except Exception as e:
            logger.error(f"Error processing notification: {e}")
