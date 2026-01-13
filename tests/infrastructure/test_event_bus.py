import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.domain.interfaces.event_bus import Event
from app.infrastructure.messaging.postgres_event_bus import PostgresEventBus


@pytest.fixture
def mock_pool() -> tuple[MagicMock, AsyncMock]:
    pool = MagicMock()

    # pool.close() is awaited
    pool.close = AsyncMock()

    conn = AsyncMock()
    # connection methods are async
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()

    # pool.acquire() is an async context manager, so it returns an object with __aenter__
    # The method acquire() itself is NOT async (it returns the context manager imediatelly)
    acquire_ctx = MagicMock()
    acquire_ctx.__aenter__ = AsyncMock(return_value=conn)
    acquire_ctx.__aexit__ = AsyncMock(return_value=None)

    pool.acquire.return_value = acquire_ctx

    return pool, conn


@pytest.mark.asyncio
async def test_subscribe_adds_handler() -> None:
    bus = PostgresEventBus()

    async def handler(event: Event) -> None:
        pass

    bus.subscribe("test_topic", handler)
    assert "test_topic" in bus._handlers
    assert handler in bus._handlers["test_topic"]


@pytest.mark.asyncio
async def test_publish_inserts_and_notifies(
    mock_pool: tuple[MagicMock, AsyncMock],
) -> None:
    pool, conn = mock_pool
    bus = PostgresEventBus()
    bus._pool = pool

    conn.fetchrow.return_value = {"id": "123-456"}

    topic = "my.topic"
    payload = {"foo": "bar"}

    await bus.publish(topic, payload)

    assert conn.fetchrow.called
    args, _ = conn.fetchrow.call_args
    assert "INSERT INTO event_queue" in args[0]
    assert args[1] == topic

    assert conn.execute.called
    notify_args, _ = conn.execute.call_args
    assert "NOTIFY bot_events" in notify_args[0]


@pytest.mark.asyncio
async def test_process_notification_calls_handler() -> None:
    bus = PostgresEventBus()
    received_event = None

    async def handler(e: Event) -> None:
        nonlocal received_event
        received_event = e

    bus.subscribe("test.topic", handler)

    payload_str = '{"topic": "test.topic", "payload": {"data": 123}}'
    await bus._process_notification(payload_str)

    assert received_event is not None
    assert received_event.topic == "test.topic"


@pytest.mark.asyncio
async def test_start_creates_pool_and_listener(
    mock_pool: tuple[MagicMock, AsyncMock],
) -> None:
    # Verify start logic
    pool_mock, conn_mock = mock_pool
    bus = PostgresEventBus()
    bus.dsn = "postgres://mock"

    with (
        patch(
            "app.infrastructure.messaging.postgres_event_bus.asyncpg.create_pool",
            new_callable=AsyncMock,
        ) as mock_create_pool,
        patch(
            "app.infrastructure.messaging.postgres_event_bus.asyncpg.connect",
            new_callable=AsyncMock,
        ) as mock_connect,
    ):
        mock_create_pool.return_value = pool_mock
        mock_connect.return_value = conn_mock  # listener connection

        async def cancel_later() -> None:
            await asyncio.sleep(0.1)
            bus._running = False

        task = asyncio.create_task(bus.start())
        await cancel_later()
        await task

        assert mock_create_pool.called
        assert mock_connect.called
        assert conn_mock.add_listener.called  # Verify listener added
