import discord
from discord.ext import commands

from app.domain.interfaces.event_bus import Event, IEventBus


class BrainCog(commands.Cog):
    def __init__(self, bot: commands.Bot, bus: IEventBus):
        self.bot = bot
        self.bus = bus

        # --- Event Subscription ---
        self.bus.subscribe("sns.update", self.on_sns_update)
        self.bus.subscribe("system.heartbeat", self.on_heartbeat)

    # --- 1. Discord -> EventBus (Ear) ---
    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        # Publish Discord message to Event Bus
        await self.bus.publish(
            "discord.message",
            {
                "author": message.author.name,
                "content": message.content,
                "channel_id": message.channel.id,
            },
        )

    # --- 2. EventBus -> Discord (Mouth) ---
    async def on_sns_update(self, event: Event) -> None:
        """Post to Discord when SNS update occurs."""
        channel_id = 1234567890  # Placeholder, should be configurable
        channel = self.bot.get_channel(channel_id)
        if channel and isinstance(channel, discord.abc.Messageable):
            text = event.payload.get("text", "")
            await channel.send(f"👀 Look what I found:\n> {text}")

    async def on_heartbeat(self, event: Event) -> None:
        """Randomly speak on heartbeat."""
        import random

        if random.random() < 0.1:  # 10% chance
            channel_id = 1234567890  # Placeholder
            channel = self.bot.get_channel(channel_id)
            if channel and isinstance(channel, discord.abc.Messageable):
                await channel.send("🍵 Just chilling...")


class BrainCogLoader:
    """Helper to load the Cog without setup() function limitation if needed."""

    pass
