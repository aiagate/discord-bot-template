import asyncio
import logging
import random

import discord
from discord.ext import commands

from app.core.events import AppEvent, EventType
from app.core.result import is_err
from app.mediator import Mediator
from app.usecases.chat.spontaneous_dialog import (
    SpontaneousDialogCommand,  # Import to ensure registration
)

logger = logging.getLogger(__name__)


async def event_consumer(queue: asyncio.Queue[AppEvent], bot: commands.Bot) -> None:
    """Consumes events from the queue."""
    logger.info("Event consumer started")
    try:
        while True:
            event = await queue.get()
            logger.debug(f"Processing event: {event.type}")

            try:
                if event.type == EventType.HEARTBEAT:
                    await _handle_heartbeat(bot)
                elif event.type == EventType.SNS_UPDATE:
                    # Future implementation
                    pass
            except Exception as e:
                logger.error(f"Error processing event {event.type}: {e}")
            finally:
                queue.task_done()

    except asyncio.CancelledError:
        logger.info("Event consumer cancelled")
        raise


async def _handle_heartbeat(bot: commands.Bot) -> None:
    """Handle heartbeat event."""
    # 30% chance to trigger spontaneous dialog
    if random.random() > 0.3:
        logger.debug("Heartbeat: Skipped spontaneous dialog (random)")
        return

    logger.info("Heartbeat: Triggering spontaneous dialog")

    command = SpontaneousDialogCommand()
    result_awaitable = Mediator.send_async(command)
    result = await result_awaitable

    if is_err(result):
        logger.error(f"Spontaneous dialog failed: {result.error}")
        return

    content, channel_id = result.unwrap()

    try:
        # Use fetch_channel for better reliability if not in cache,
        # but get_channel is sync and faster if in cache.
        channel = bot.get_channel(int(channel_id))
        if not channel:
            try:
                channel = await bot.fetch_channel(int(channel_id))
            except discord.NotFound:
                logger.warning(f"Target channel {channel_id} not found")
                return

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            await channel.send(content)
        else:
            logger.warning(f"Channel {channel_id} is not a text channel")

    except Exception as e:
        logger.error(f"Failed to send spontaneous message: {e}")
