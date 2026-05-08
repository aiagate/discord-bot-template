"""Event handlers for Worker."""

import logging
from typing import Any

from flow_med import Mediator

from app.presentation.worker.registry import event_handler, scheduled_task
from app.usecases.users.welcome_user import WelcomeUserCommand

logger = logging.getLogger(__name__)


@event_handler("user.created")
async def on_user_created(payload: dict[str, Any]) -> None:
    """Handle user.created event."""
    user_id = payload.get("user_id")
    if not user_id:
        return

    # Mediatorを介してUseCaseを実行
    await Mediator.send_async(WelcomeUserCommand(user_id=user_id))


@event_handler("example.topic")
async def on_example_event(payload: dict[str, Any]) -> None:
    """Example of another handler."""
    logger.info(f"Received example event with payload: {payload}")


@scheduled_task(interval_seconds=60)
async def example_scheduled_task() -> None:
    """Example of a periodic background task."""
    logger.info("Executing scheduled background task (every 60s)")
