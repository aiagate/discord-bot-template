import inspect

import discord
from discord.ext import commands

from app.core.mediator import Mediator
from app.core.result import is_ok
from app.domain.decorators import event_listener
from app.domain.interfaces.event_bus import Event, IEventBus
from app.usecases.messaging.process_sns_update import ProcessSnsUpdateCommand
from app.usecases.messaging.publish_received_message import (
    PublishReceivedMessageCommand,
)


class BrainCog(commands.Cog):
    def __init__(self, bot: commands.Bot, bus: IEventBus) -> None:
        self.bot = bot
        self.bus = bus

        # --- Event Subscription ---
        for _, member in inspect.getmembers(self):
            if hasattr(member, "_event_bus_topic"):
                topic = member._event_bus_topic
                self.bus.subscribe(topic, member)

    # --- 1. Discord -> EventBus (Ear) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        await Mediator.send_async(
            PublishReceivedMessageCommand(
                author=message.author.name,
                content=message.content,
                channel_id=message.channel.id,
            )
        )

    # --- 2. EventBus -> Discord (Mouth) ---
    @event_listener("sns.update")
    async def on_sns_update(self, event: Event) -> None:
        """Post to Discord when SNS update occurs."""
        channel_id = 1234567890  # Placeholder
        channel = self.bot.get_channel(channel_id)
        if channel and isinstance(channel, discord.abc.Messageable):
            result = await Mediator.send_async(
                ProcessSnsUpdateCommand(payload=event.payload)
            )
            if is_ok(result):
                dto = result.unwrap()
                if dto.content:
                    await channel.send(dto.content)

    @event_listener("bot.speak")
    async def on_bot_speak(self, event: Event) -> None:
        """Speak when Worker instructs to."""
        channel_id = event.payload.get("channel_id")
        content = event.payload.get("content")

        if not channel_id or not content:
            return

        channel = self.bot.get_channel(channel_id)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(channel_id)
            except discord.NotFound:
                return

        if channel and isinstance(channel, discord.abc.Messageable):
            await channel.send(content)


class BrainCogLoader:
    """Helper to load the Cog without setup() function limitation if needed."""

    pass
