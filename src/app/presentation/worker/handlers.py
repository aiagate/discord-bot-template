"""Event handlers for Worker."""

import logging
from collections.abc import Mapping

from flow_med import Mediator

from app.presentation.worker.registry import event_handler, scheduled_task
from app.usecases.users.welcome_user import WelcomeUserCommand

logger = logging.getLogger(__name__)


@event_handler("user.created")
async def on_user_created(payload: Mapping[str, object]) -> None:
    """Handle user.created event."""
    user_id = payload.get("user_id")
    if not isinstance(user_id, str) or not user_id:
        return

    # Mediatorを介してUseCaseを実行
    await Mediator.send_async(WelcomeUserCommand(user_id=user_id))


@event_handler("example.topic")
async def on_example_event(payload: Mapping[str, object]) -> None:
    """Example of another handler."""
    logger.info(f"Received example event with payload: {payload}")


@scheduled_task(interval_seconds=60)
async def example_scheduled_task() -> None:
    """Example of a periodic background task."""
    logger.info("Executing scheduled background task (every 60s)")
