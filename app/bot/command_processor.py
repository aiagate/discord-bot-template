import asyncio
import logging
from collections.abc import Callable

import discord
from discord.ext import commands

from app.core.interfaces.notification_listener import INotificationListener
from app.domain.aggregates.command import Command
from app.domain.repositories.interfaces import IUnitOfWork

logger = logging.getLogger(__name__)


async def command_processor(
    bot: commands.Bot,
    uow_factory: Callable[[], IUnitOfWork],
    listener: INotificationListener,
) -> None:
    """Polls the command outbox and executes commands using LISTEN/NOTIFY."""
    logger.info("Command processor started (LISTEN/NOTIFY mode)")

    channel = "new_command_outbox_item"

    try:
        await listener.start(channel)

        try:
            while True:
                # 2. Process all pending items first
                while True:
                    processed = await _process_one_command(bot, uow_factory)
                    if not processed:
                        break

                # 3. Wait for notification
                try:
                    logger.debug("💤 Waiting for commands...")
                    await listener.wait(timeout=600)
                    logger.debug("⚡ Notification received!")
                except TimeoutError:
                    # Just a wakeup check
                    pass

        finally:
            await listener.stop()

    except asyncio.CancelledError:
        logger.info("Command processor cancelled")
        raise
    except Exception as e:
        logger.error(f"Command processor fatal error: {e}")
        await asyncio.sleep(5)


async def _process_one_command(
    bot: commands.Bot, uow_factory: Callable[[], IUnitOfWork]
) -> bool:
    """Pop and execute one command. Returns True if a command was processed."""
    async with uow_factory() as uow:
        repo = uow.GetRepository(Command)
        command = await repo.dequeue()

        if not command:
            await uow.commit()
            return False

        logger.debug(f"Processing command: {command.type}")

        try:
            if command.type == "SEND_DISCORD_MESSAGE":
                channel_id = command.payload.get("channel_id")
                content = command.payload.get("content")

                if channel_id and content:
                    await _send_message(bot, int(channel_id), content)

            await repo.complete(command.id)
            await uow.commit()
            return True

        except Exception as e:
            logger.error(f"Error processing command {command.id}: {e}")
            await repo.fail(command.id)
            await uow.commit()
            return True


async def _send_message(bot: commands.Bot, channel_id: int, content: str) -> None:
    """Send message to Discord channel."""
    try:
        channel = bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await bot.fetch_channel(channel_id)
            except discord.NotFound:
                logger.warning(f"Target channel {channel_id} not found")
                return

        if isinstance(channel, (discord.TextChannel, discord.Thread)):
            await channel.send(content)
        else:
            logger.warning(f"Channel {channel_id} is not a text channel")

    except Exception as e:
        logger.error(f"Discord send error: {e}")
        raise e
