import asyncio
import json
import logging
import os
from typing import Any

import redis.asyncio as redis
from app.core.result import Err, Ok, Result
from redis.asyncio.client import PubSub

from app.domain.interfaces.event_bus import Event, EventHandler, IEventBus

logger = logging.getLogger(__name__)


class RedisEventBus(IEventBus):
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

    def subscribe(self, topic: str, handler: EventHandler) -> None:
        is_new_topic = topic not in self._handlers
        if is_new_topic:
            self._handlers[topic] = []

        self._handlers[topic].append(handler)
        logger.debug(f"Subscribed to topic: {topic}")

        if is_new_topic and self._running and self._pubsub:
            asyncio.create_task(self._subscribe_topic(topic))

    async def publish(
        self, topic: str, payload: dict[str, Any]
    ) -> Result[None, Exception]:
        if not self._redis:
            msg = f"Redis EventBus not started (redis_url={self.redis_url}), cannot publish event: {topic}"
            logger.warning(msg)
            return Err(RuntimeError(msg))

        try:
            # We publish the full event structure as JSON
            message = {"topic": topic, "payload": payload}
            await self._redis.publish(topic, json.dumps(message))
            logger.debug(f"Published event to Redis: {topic}")
            return Ok(None)
        except Exception as e:
            logger.error(f"Failed to publish event {topic}: {e}")
            return Err(e)

    async def start(self) -> Result[None, Exception]:
        if not self.redis_url:
            logger.error("REDIS_URL not set, cannot start EventBus.")
            return Err(RuntimeError("REDIS_URL not set"))

        self._running = True
        try:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            logger.info(f"Connected to Redis at {self.redis_url}")

            # Start the listener task
            self._listening_task = asyncio.create_task(self._listener())
            return Ok(None)

        except Exception as e:
            logger.error(f"Error starting Redis EventBus: {e}")
            return Err(e)

    async def _listener(self) -> None:
        if not self._redis:
            return

        self._pubsub = self._redis.pubsub()

        # Subscribe to all existing topics
        for topic in self._handlers:
            await self._subscribe_topic(topic)

        async for message in self._pubsub.listen():
            if not self._running:
                break

            if message["type"] in ("message", "pmessage"):
                await self._process_message(message)

    async def _process_message(self, message: dict[str, Any]) -> None:
        try:
            channel = message["channel"]
            data = message["data"]

            parsed_data = json.loads(data)
            topic_in_msg = parsed_data.get("topic")
            payload = parsed_data.get("payload", {})

            # Dispatch to specific match
            if topic_in_msg:
                await self._dispatch(topic_in_msg, topic_in_msg, payload)

            # Dispatch to pattern match if present
            if message["type"] == "pmessage":
                matched_pattern = message["pattern"]
                if matched_pattern and matched_pattern != topic_in_msg:
                    real_topic = topic_in_msg or channel
                    await self._dispatch(matched_pattern, real_topic, payload)

        except json.JSONDecodeError:
            logger.error(f"Failed to decode Redis message: {message.get('data')}")
        except Exception as e:
            logger.error(f"Error processing Redis message: {e}")

    async def stop(self) -> Result[None, Exception]:
        try:
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
            return Ok(None)
        except Exception as e:
            return Err(e)

    async def _dispatch(
        self, handler_key: str, event_topic: str, payload: dict[str, Any]
    ) -> None:
        if handlers := self._handlers.get(handler_key):
            event = Event(topic=event_topic, payload=payload)
            for handler in handlers:
                try:
                    await handler(event)
                except Exception as e:
                    logger.error(f"Error in event handler for {handler_key}: {e}")
