"""Regression tests for event handler failure observability."""

import asyncio
import logging
import traceback
from collections.abc import Mapping

import pytest
from anyio import fail_after

from app.infrastructure.messaging.in_memory_event_bus import InMemoryEventBus

_EVENT_BUS_LOGGER = "app.infrastructure.messaging.in_memory_event_bus"
_EVENT_TIMEOUT_SECONDS = 1.0
_PAYLOAD_SENTINEL = "private-payload-sentinel-6f1c2d9e"


async def _join_queue(bus: InMemoryEventBus) -> None:
    """Wait until the worker has finished every queued event."""
    with fail_after(_EVENT_TIMEOUT_SECONDS):
        await bus._queue.join()


async def _wait_for_event(event: asyncio.Event) -> None:
    """Wait for a handler signal without allowing the test to hang."""
    with fail_after(_EVENT_TIMEOUT_SECONDS):
        await event.wait()


async def _stop_bus(bus: InMemoryEventBus) -> None:
    """Stop the bus with a bound so cleanup cannot hang the suite."""
    with fail_after(_EVENT_TIMEOUT_SECONDS):
        await bus.stop()


def _event_bus_errors(
    caplog: pytest.LogCaptureFixture,
) -> list[logging.LogRecord]:
    """Return ERROR records emitted by the in-memory event bus logger."""
    return [
        record
        for record in caplog.records
        if record.name == _EVENT_BUS_LOGGER and record.levelno == logging.ERROR
    ]


def _record_text(record: logging.LogRecord) -> str:
    """Format a record's message together with its exception traceback."""
    text = record.getMessage()
    exc_info = record.exc_info
    if exc_info is None:
        return text

    exc_type, exc_value, exc_tb = exc_info
    if exc_type is None or exc_value is None:
        return text

    return f"{text}\n{''.join(traceback.format_exception(exc_type, exc_value, exc_tb))}"


def _assert_single_failure_log(
    caplog: pytest.LogCaptureFixture,
    *,
    topic: str,
    handler_name: str,
    exception_type: str,
    exception_message: str,
) -> None:
    """Assert the contract for one observable subscriber failure."""
    errors = _event_bus_errors(caplog)
    assert len(errors) == 1

    record = errors[0]
    message = record.getMessage()
    text = _record_text(record)

    assert topic in message
    assert handler_name in message
    assert record.exc_info is not None
    assert exception_type in text
    assert exception_message in text
    assert _PAYLOAD_SENTINEL not in text


@pytest.mark.anyio
async def test_failing_handler_does_not_prevent_other_handlers(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful and failing subscribers both run when one raises."""
    topic = "orders.created"
    success_called = asyncio.Event()
    failure_called = asyncio.Event()

    async def succeeding_handler(_payload: Mapping[str, object]) -> None:
        success_called.set()

    async def failing_handler(_payload: Mapping[str, object]) -> None:
        failure_called.set()
        raise RuntimeError("subscriber failed")

    bus = InMemoryEventBus()
    with caplog.at_level(logging.ERROR, logger=_EVENT_BUS_LOGGER):
        try:
            await bus.start()
            await bus.subscribe(topic, succeeding_handler)
            await bus.subscribe(topic, failing_handler)
            await bus.publish(
                topic,
                {"order_id": "order-1", "private": _PAYLOAD_SENTINEL},
            )
            await _join_queue(bus)
        finally:
            await _stop_bus(bus)

    assert success_called.is_set()
    assert failure_called.is_set()
    _assert_single_failure_log(
        caplog,
        topic=topic,
        handler_name="failing_handler",
        exception_type="RuntimeError",
        exception_message="subscriber failed",
    )


@pytest.mark.anyio
async def test_later_queued_event_runs_after_handler_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A subscriber failure does not stop later queued events."""
    failing_topic = "orders.created"
    later_topic = "orders.shipped"
    failure_called = asyncio.Event()
    later_called = asyncio.Event()

    async def failing_handler(_payload: Mapping[str, object]) -> None:
        failure_called.set()
        raise RuntimeError("subscriber failed")

    async def later_handler(_payload: Mapping[str, object]) -> None:
        later_called.set()

    bus = InMemoryEventBus()
    with caplog.at_level(logging.ERROR, logger=_EVENT_BUS_LOGGER):
        try:
            await bus.start()
            await bus.subscribe(failing_topic, failing_handler)
            await bus.subscribe(later_topic, later_handler)
            await bus.publish(
                failing_topic,
                {"order_id": "order-1", "private": _PAYLOAD_SENTINEL},
            )
            await bus.publish(
                later_topic,
                {"shipment_id": "shipment-1", "private": _PAYLOAD_SENTINEL},
            )
            await _join_queue(bus)
        finally:
            await _stop_bus(bus)

    assert failure_called.is_set()
    assert later_called.is_set()
    _assert_single_failure_log(
        caplog,
        topic=failing_topic,
        handler_name="failing_handler",
        exception_type="RuntimeError",
        exception_message="subscriber failed",
    )


@pytest.mark.anyio
async def test_callable_object_handler_failure_is_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Callable handlers are identified without relying on ``__name__``."""
    topic = "orders.created"

    class _ExplodingHandler:
        """Fail as a callable object that has no ``__name__`` attribute."""

        async def __call__(self, _payload: Mapping[str, object]) -> None:
            raise ValueError("callable subscriber failed")

    bus = InMemoryEventBus()
    with caplog.at_level(logging.ERROR, logger=_EVENT_BUS_LOGGER):
        try:
            await bus.start()
            await bus.subscribe(topic, _ExplodingHandler())
            await bus.publish(
                topic,
                {"order_id": "order-1", "private": _PAYLOAD_SENTINEL},
            )
            await _join_queue(bus)
        finally:
            await _stop_bus(bus)

    _assert_single_failure_log(
        caplog,
        topic=topic,
        handler_name="_ExplodingHandler",
        exception_type="ValueError",
        exception_message="callable subscriber failed",
    )


@pytest.mark.anyio
async def test_all_successful_handlers_emit_no_error_logs(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Successful dispatch never produces an event bus error log."""
    topic = "orders.created"
    first_called = asyncio.Event()
    second_called = asyncio.Event()

    async def first_handler(_payload: Mapping[str, object]) -> None:
        first_called.set()

    async def second_handler(_payload: Mapping[str, object]) -> None:
        second_called.set()

    bus = InMemoryEventBus()
    with caplog.at_level(logging.ERROR, logger=_EVENT_BUS_LOGGER):
        try:
            await bus.start()
            await bus.subscribe(topic, first_handler)
            await bus.subscribe(topic, second_handler)
            await bus.publish(
                topic,
                {"order_id": "order-1", "private": _PAYLOAD_SENTINEL},
            )
            await _join_queue(bus)
        finally:
            await _stop_bus(bus)

    assert first_called.is_set()
    assert second_called.is_set()
    assert _event_bus_errors(caplog) == []


@pytest.mark.anyio
async def test_cancellation_during_stop_is_not_a_subscriber_failure(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Cancelling an in-flight handler on stop is not logged as a failure."""
    topic = "orders.created"
    handler_started = asyncio.Event()
    never_set = asyncio.Event()

    async def blocking_handler(_payload: Mapping[str, object]) -> None:
        handler_started.set()
        await never_set.wait()

    bus = InMemoryEventBus()
    with caplog.at_level(logging.ERROR, logger=_EVENT_BUS_LOGGER):
        try:
            await bus.start()
            await bus.subscribe(topic, blocking_handler)
            await bus.publish(
                topic,
                {"order_id": "order-1", "private": _PAYLOAD_SENTINEL},
            )
            await _wait_for_event(handler_started)
        finally:
            await _stop_bus(bus)

    assert _event_bus_errors(caplog) == []


@pytest.mark.anyio
async def test_failure_is_logged_before_a_parallel_handler_is_cancelled(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A slow peer cannot delay or erase another subscriber's failure log."""
    topic = "orders.created"
    blocking_started = asyncio.Event()
    failure_raised = asyncio.Event()
    blocking_cancelled = asyncio.Event()
    never_set = asyncio.Event()

    async def failing_handler(_payload: Mapping[str, object]) -> None:
        await blocking_started.wait()
        failure_raised.set()
        raise RuntimeError("subscriber failed before stop")

    async def blocking_handler(_payload: Mapping[str, object]) -> None:
        blocking_started.set()
        try:
            await never_set.wait()
        except asyncio.CancelledError:
            blocking_cancelled.set()
            raise

    bus = InMemoryEventBus()
    with caplog.at_level(logging.ERROR, logger=_EVENT_BUS_LOGGER):
        try:
            await bus.subscribe(topic, failing_handler)
            await bus.subscribe(topic, blocking_handler)
            await bus.start()
            await bus.publish(topic, {"private": _PAYLOAD_SENTINEL})
            await _wait_for_event(failure_raised)
            assert not blocking_cancelled.is_set()
            _assert_single_failure_log(
                caplog,
                topic=topic,
                handler_name="failing_handler",
                exception_type="RuntimeError",
                exception_message="subscriber failed before stop",
            )
        finally:
            await _stop_bus(bus)

    assert blocking_cancelled.is_set()
    _assert_single_failure_log(
        caplog,
        topic=topic,
        handler_name="failing_handler",
        exception_type="RuntimeError",
        exception_message="subscriber failed before stop",
    )
