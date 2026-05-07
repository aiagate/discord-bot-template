import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as redis
from redis.asyncio.client import PubSub

from app.domain.interfaces.event_bus import EventHandler, IEventBus

logger = logging.getLogger(__name__)


class RedisEventBus(IEventBus):
    """Redis Pub/Subを用いたイベントバスの実装。

    複数プロセス間での高速なリアルタイム・メッセージングに適しています。    Fire-and-Forgetのため、購読者がいない状態で送信されたメッセージは消えます。
    """

    def __init__(self) -> None:
        self._handlers: dict[str, list[EventHandler]] = {}
        self._redis: redis.Redis | None = None
        self._pubsub: PubSub | None = None
        self._running = False
        self._listening_task: asyncio.Task[None] | None = None

        self.redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

    def _is_pattern(self, topic: str) -> bool:
        return "*" in topic or "?" in topic

    async def _subscribe_topic(self, topic: str) -> None:
        if not self._pubsub:
            return
        try:
            if self._is_pattern(topic):
                await self._pubsub.psubscribe(topic)
                logger.info(f"Redis PubSub psubscribed to: {topic}")
            else:
                await self._pubsub.subscribe(topic)
                logger.info(f"Redis PubSub subscribed to: {topic}")
        except Exception as e:
            logger.error(f"Failed to subscribe to {topic}: {e}")

    async def subscribe(self, topic: str, handler: EventHandler) -> None:
        is_new_topic = topic not in self._handlers
        if is_new_topic:
            self._handlers[topic] = []

        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed to topic: {topic}")

        if is_new_topic and self._running and self._pubsub:
            asyncio.create_task(self._subscribe_topic(topic))

    async def publish(self, topic: str, payload: dict[str, Any]) -> None:
        if not self._redis:
            msg = f"Redis EventBus not started (redis_url={self.redis_url}), cannot publish event: {topic}"
            logger.warning(msg)
            raise RuntimeError(msg)

        try:
            message = {"topic": topic, "payload": payload}
            await self._redis.publish(topic, json.dumps(message))
            logger.debug(f"Published event to Redis: {topic}")
        except Exception as e:
            logger.error(f"Failed to publish event {topic}: {e}")
            raise e

    async def start(self) -> None:
        if not self.redis_url:
            logger.error("REDIS_URL not set, cannot start EventBus.")
            raise RuntimeError("REDIS_URL not set")

        self._running = True
        try:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"Connected to Redis at {self.redis_url}")

            self._listening_task = asyncio.create_task(self._listener())
        except Exception as e:
            logger.error(f"Error starting Redis EventBus: {e}")
            raise e

    async def _listener(self) -> None:
        if not self._redis:
            return

        self._pubsub = self._redis.pubsub()

        for topic in self._handlers:
            await self._subscribe_topic(topic)

        async for message in self._pubsub.listen():
            if not self._running:
                break

            if message["type"] in ("message", "pmessage"):
                await self._process_message(message)

    async def _process_message(self, message: dict[str, Any]) -> None:
        try:
            data = message["data"]
            parsed_data = json.loads(data)
            topic_in_msg = parsed_data.get("topic")
            payload = parsed_data.get("payload", {})

            if topic_in_msg:
                await self._dispatch(topic_in_msg, payload)

            if message["type"] == "pmessage":
                matched_pattern = message["pattern"]
                if matched_pattern and matched_pattern != topic_in_msg:
                    await self._dispatch(matched_pattern, payload)

        except json.JSONDecodeError:
            logger.error(f"Failed to decode Redis message: {message.get('data')}")
        except Exception as e:
            logger.error(f"Error processing Redis message: {e}")

    async def stop(self) -> None:
        self._running = False
        if self._pubsub:
            await self._pubsub.close()
        if self._redis:
            await self._redis.close()
        if self._listening_task:
            self._listening_task.cancel()
            try:
                await self._listening_task
            except asyncio.CancelledError:
                pass

    async def _dispatch(self, handler_key: str, payload: dict[str, Any]) -> None:
        if handlers := self._handlers.get(handler_key):
            # 複数ハンドラがある場合は並行実行する
            await asyncio.gather(
                *[handler(payload) for handler in handlers], return_exceptions=True
            )
