import asyncio
import logging
import os
from typing import Any

import asyncpg

from app.core.interfaces.notification_listener import INotificationListener

logger = logging.getLogger(__name__)


class PostgresNotificationListener(INotificationListener):
    def __init__(self) -> None:
        self._conn: asyncpg.Connection | None = None
        self._notification_event = asyncio.Event()

    async def start(self, channel: str) -> None:
        db_url = os.getenv("DATABASE_URL")
        if not db_url:
            raise ValueError("DATABASE_URL not set")

        dsn = db_url.replace("postgresql+asyncpg://", "postgresql://")

        try:
            self._conn = await asyncpg.connect(dsn)
            if not self._conn:
                raise RuntimeError(
                    "Failed to connect to database in PostgresNotificationListener"
                )
            await self._conn.add_listener(channel, self._listener)
            logger.info(f"Listening on channel: {channel}")
        except Exception as e:
            logger.error(f"Failed to start Postgres listener: {e}")
            raise

    def _listener(self, *args: Any) -> None:
        self._notification_event.set()

    async def wait(self, timeout: float | None = None) -> None:
        if not self._conn:
            raise RuntimeError("Listener not started")

        self._notification_event.clear()
        await asyncio.wait_for(self._notification_event.wait(), timeout=timeout)

    async def stop(self) -> None:
        if self._conn:
            await self._conn.close()
            self._conn = None
            logger.info("Postgres listener stopped")
