import asyncio
import json
import logging
import os
from typing import Any

import asyncpg

from app.domain.interfaces.event_bus import EventHandler, IEventBus

logger = logging.getLogger(__name__)


class PostgresEventBus(IEventBus):
    """PostgreSQLのLISTEN/NOTIFYを用いたイベントバスの実装。

    プロセス間通信をDBのみで行いたい場合に適しています。    ※本実装はNOTIFYを直接発行する軽量版です。イベントの永続化が必要な場合は
    別途テーブルへのINSERTを併用する設計に変更可能です。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._pool: asyncpg.Pool | None = None
        self._listener_conn: asyncpg.Connection | None = None
        self._listener_task: asyncio.Task[None] | None = None
        self._running = False

        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            self.dsn = ""
        else:
            # asyncpg requires postgresql:// instead of postgresql+asyncpg://
            self.dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

    async def subscribe(self, topic: str, handler: EventHandler) -> None:
        if topic not in self._handlers:
            self._handlers[topic] = []
        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed to topic: {topic}")

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not self._pool:
            msg = "EventBus not started, cannot publish events."
            logger.warning(msg)
            raise RuntimeError(msg)

        async with self._pool.acquire() as conn:
            try:
                notify_payload = json.dumps(
                    {
                        "topic": topic,
                        "payload": payload,
                    }
                )
                await conn.execute("SELECT pg_notify('bot_events', $1)", notify_payload)
                logger.debug(f"Published event: {topic}")
            except Exception as e:
                logger.error(f"Failed to publish event {topic}: {e}")
                raise e

    async def start(self) -> None:
        if not self.dsn:
            msg = "DATABASE_URL not set, cannot start Postgres EventBus."
            logger.error(msg)
            raise RuntimeError(msg)

        if not self.dsn.startswith("postgresql"):
            msg = "PostgresEventBus requires a postgresql database URL."
            logger.error(msg)
            raise RuntimeError(msg)

        self._running = True
        try:
            self._pool = await asyncpg.create_pool(self.dsn)
            logger.info("EventBus connection pool created.")

            self._listener_conn = await asyncpg.connect(self.dsn)

            async def _listener(
                connection: Any, pid: int, channel: str, payload: str
            ) -> None:
                asyncio.create_task(self._process_notification(payload))

            if self._listener_conn:
                await self._listener_conn.add_listener("bot_events", _listener)
            logger.info("Postgres Event Bus Started. Listening on 'bot_events'.")

            self._listener_task = asyncio.create_task(self._keep_alive())
        except Exception as e:
            logger.error(f"Error in EventBus start: {e}")
            raise e

    async def _keep_alive(self) -> None:
        while self._running:
            await asyncio.sleep(1)

    async def stop(self) -> None:
        self._running = False
        if self._listener_task:
            self._listener_task.cancel()
            try:
                await self._listener_task
            except asyncio.CancelledError:
                pass

        if self._listener_conn:
            await self._listener_conn.close()

        if self._pool:
            await self._pool.close()

    async def _process_notification(self, raw_payload: str) -> None:
        try:
            data = json.loads(raw_payload)
            topic = data.get("topic")
            payload = data.get("payload", {})

            if not topic:
                logger.warning("Received notification without topic.")
                return

            if handlers := self._handlers.get(topic):
                await asyncio.gather(
                    *[handler(payload) for handler in handlers], return_exceptions=True
                )
        except json.JSONDecodeError:
            logger.error(f"Failed to decode notification payload: {raw_payload}")
        except Exception as e:
            logger.error(f"Error processing notification: {e}")
