"""A single master's Discord window onto ongoing support."""

import time

import discord

from app.contracts.messages.support import RuntimeObservation
from app.infrastructure.store import LocalStore


class DiscordGateway(discord.Client):
    """Receive inputs and connection events; all replies use the saved outbox."""

    def __init__(
        self, store: LocalStore, activity_id: str, channel_id: int, master_id: int
    ) -> None:
        intents = discord.Intents.default()
        intents.message_content = True
        super().__init__(intents=intents)
        store.current(activity_id)
        self.store = store
        self.activity_id = activity_id
        self.channel_id = channel_id
        self.master_id = master_id

    async def on_ready(self) -> None:
        """Record an observed Gateway connection without claiming future health."""
        self.store.observe(
            RuntimeObservation(
                component="discord",
                status="success",
                observed_at=time.time(),
                source="DiscordGateway.on_ready",
            )
        )

    async def on_resumed(self) -> None:
        """Record the Gateway's successful session resumption."""
        self.store.observe(
            RuntimeObservation(
                component="discord",
                status="success",
                observed_at=time.time(),
                source="DiscordGateway.on_resumed",
            )
        )

    async def on_disconnect(self) -> None:
        """Distinguish loss of connection from absent configuration."""
        self.store.observe(
            RuntimeObservation(
                component="discord",
                status="disconnected",
                observed_at=time.time(),
                source="DiscordGateway.on_disconnect",
            )
        )

    async def on_message(self, message: discord.Message) -> None:
        """Accept one master's original input, ignoring bots and webhooks."""
        if (
            message.author.bot
            or message.webhook_id
            or message.channel.id != self.channel_id
            or message.author.id != self.master_id
        ):
            return
        content = message.content
        if content in {"!stop", "!resume", "!status"}:
            self.store.command(
                self.activity_id, content, external_key=f"discord:{message.id}"
            )
        elif content.strip():
            self.store.receive(
                self.activity_id, content, external_key=f"discord:{message.id}"
            )
