"""One webhook speaks for every character, with durable delivery confirmation."""

import asyncio
import io
import time
from datetime import UTC, datetime
from typing import Any

import discord

from app.contracts.messages.support import (
    Character,
    DeliveryAttempt,
    DeliveryReceipt,
    DiscordDestination,
    Notice,
    RuntimeObservation,
)
from app.infrastructure.store import LocalStore


class DiscordWebhookPublisher:
    """Publish saved speech through a validated, persistent Discord window."""

    def __init__(
        self, store: LocalStore, client: discord.Client, url: str, channel_id: int
    ) -> None:
        try:
            self._webhook = discord.Webhook.from_url(url, client=client)
        except ValueError:
            raise ValueError("DISCORD_WEBHOOK_URLの形式が不正です。") from None
        self.store = store
        self.client = client
        self.channel_id = channel_id
        self._destination: DiscordDestination | None = None

    async def _validate(self) -> discord.TextChannel | discord.Thread:
        remote = await self._webhook.fetch(prefer_auth=False)
        channel = await self.client.fetch_channel(self.channel_id)
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            raise ValueError(
                "送信先にはテキストチャンネルか投稿スレッドを指定してください。"
            )
        parent = channel
        if isinstance(channel, discord.Thread):
            parent = await self.client.fetch_channel(channel.parent_id)
        if (
            not isinstance(parent, (discord.TextChannel, discord.ForumChannel))
            or remote.type != discord.WebhookType.incoming
            or remote.id != self._webhook.id
            or remote.channel_id != parent.id
            or remote.guild_id != channel.guild.id
            or parent.guild.id != channel.guild.id
        ):
            raise ValueError("Webhookと送信先が一致しません。")
        destination = DiscordDestination(
            guild_id=channel.guild.id, channel_id=channel.id, webhook_id=remote.id
        )
        if self._destination is not None and self._destination != destination:
            raise ValueError("Webhookの送信先が変更されています。")
        self.store.observe(
            RuntimeObservation(
                component="webhook",
                status="success",
                observed_at=time.time(),
                source="DiscordWebhookPublisher.validate",
            )
        )
        return channel

    async def initialize(self) -> None:
        """Validate and bind the window before starting work or accepting inputs."""
        try:
            async with asyncio.timeout(30):
                channel = await self._validate()
                destination = DiscordDestination(
                    guild_id=channel.guild.id,
                    channel_id=channel.id,
                    webhook_id=self._webhook.id,
                )
                self.store.bind_discord(destination)
                self._destination = destination
        except Exception:
            self._failed_validation()
            raise ValueError(
                "Webhookの送信先を確認できません。設定と保存済みの宛先を確認してください。"
            ) from None

    def _failed_validation(self) -> None:
        self.store.observe(
            RuntimeObservation(
                component="webhook",
                status="failure",
                observed_at=time.time(),
                source="DiscordWebhookPublisher.validate",
            )
        )

    def _receipt(
        self, message: discord.Message | discord.WebhookMessage
    ) -> DeliveryReceipt:
        if (
            message.channel.id != self.channel_id
            or message.webhook_id != self._webhook.id
        ):
            raise ValueError("確認結果の送信先または送信者が一致しません。")
        return DeliveryReceipt(
            message_id=str(message.id),
            channel_id=str(message.channel.id),
            sender_id=str(message.webhook_id),
            username=message.author.display_name,
            content=message.content,
            created_at=message.created_at.timestamp(),
        )

    async def send(self, notice: Notice, character: Character) -> DeliveryReceipt:
        """Confirm saved or interrupted sends before permitting another request."""
        files: list[discord.File] = []
        try:
            if self._destination is None:
                raise ValueError("Webhookの送信先が未初期化です。")
            attempt = self.store.discord_attempt(notice.id)
            if attempt is not None and attempt.receipt is not None:
                return attempt.receipt
            try:
                channel = await self._validate()
            except Exception:
                self._failed_validation()
                raise
            marker = f"support:{notice.id}"
            if attempt is not None:
                async for message in channel.history(
                    after=datetime.fromtimestamp(max(0, attempt.started_at - 1), UTC),
                    oldest_first=True,
                    limit=None,
                ):
                    if message.webhook_id == self._webhook.id and any(
                        embed.footer.text == marker for embed in message.embeds
                    ):
                        receipt = self._receipt(message)
                        self.store.save_discord_attempt(
                            notice.id, attempt.model_copy(update={"receipt": receipt})
                        )
                        return receipt
                raise RuntimeError("前回の配信が未確認です。自動再送は行いません。")
            text = notice.rendered or notice.content
            content = text.encode("utf-16-le")[:3800].decode(
                "utf-16-le", errors="ignore"
            )
            if content != text:
                files.append(
                    discord.File(io.BytesIO(text.encode()), filename="report.txt")
                )
                content += "\n\n全文は添付のreport.txtにあります。"
            marker_embed = discord.Embed()
            marker_embed.set_footer(text=marker)
            options: dict[str, Any] = {
                "content": content,
                "username": character.name,
                "embed": marker_embed,
                "files": files,
                "allowed_mentions": discord.AllowedMentions.none(),
                "wait": True,
            }
            if character.avatar_url is not None:
                options["avatar_url"] = character.avatar_url
            if isinstance(channel, discord.Thread):
                options["thread"] = discord.Object(id=channel.id)
            attempt = DeliveryAttempt(started_at=time.time())
            self.store.save_discord_attempt(notice.id, attempt)
            try:
                sent = await self._webhook.send(**options)
            except discord.HTTPException as error:
                if 400 <= error.status < 500 and error.status != 429:
                    self.store.reset_discord_attempt(notice.id)
                raise
            if sent is None:
                raise RuntimeError("Discordの送信確認がありません。")
            receipt = self._receipt(sent)
            self.store.save_discord_attempt(
                notice.id, attempt.model_copy(update={"receipt": receipt})
            )
            return receipt
        except Exception:
            raise RuntimeError(
                "Webhook配信を確認できません。保存した通知と試行を保持します。"
            ) from None
        finally:
            for file in files:
                file.close()
                file.fp.close()
