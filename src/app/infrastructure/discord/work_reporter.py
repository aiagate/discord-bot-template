"""Send verified work reports through configured character webhooks."""

import asyncio
import io
from typing import Any

import discord

from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkAttachment,
)
from app.contracts.messages.speech_message import PublishedSpeech
from app.contracts.ports.character_work import ICharacterWorkReporter
from app.domain.characters import CharacterDefinition
from app.domain.value_objects import DiscordConversationScope


class DiscordWorkReporter(ICharacterWorkReporter):
    """Route one report and its files to the original channel or thread."""

    def __init__(
        self, urls: tuple[str, ...], client: discord.Client, guild_id: str
    ) -> None:
        if not urls:
            raise ValueError("Configure character work webhook URLs.")
        try:
            self._webhooks = tuple(
                discord.Webhook.from_url(url, client=client) for url in urls
            )
        except ValueError:
            raise ValueError("Invalid character work webhook URL.") from None
        self._client = client
        self._guild_id = guild_id
        self._destinations: dict[int, discord.Webhook] = {}

    @property
    def webhook_ids(self) -> tuple[int, ...]:
        """Return webhook identities that the listener must not ingest again."""
        return tuple(webhook.id for webhook in self._webhooks)

    async def initialize(self, channel_ids: frozenset[str]) -> frozenset[str]:
        """Validate routes and return explicit or webhook-derived work channels."""
        async with asyncio.timeout(30):
            destinations: dict[int, discord.Webhook] = {}
            for webhook in self._webhooks:
                remote = await webhook.fetch(prefer_auth=False)
                if str(remote.guild_id) != self._guild_id or remote.channel_id is None:
                    raise ValueError("Work webhook belongs to another guild.")
                if remote.channel_id in destinations:
                    raise ValueError("Configure one work webhook per parent channel.")
                parent = await self._client.fetch_channel(remote.channel_id)
                if (
                    not isinstance(parent, (discord.TextChannel, discord.ForumChannel))
                    or str(parent.guild.id) != self._guild_id
                ):
                    raise ValueError("Work webhook requires a text or forum channel.")
                destinations[remote.channel_id] = webhook
            for channel_id in channel_ids:
                channel = await self._client.fetch_channel(int(channel_id))
                if (
                    not isinstance(
                        channel,
                        (discord.TextChannel, discord.Thread, discord.ForumChannel),
                    )
                    or str(channel.guild.id) != self._guild_id
                ):
                    raise ValueError("Work channel belongs to another guild.")
                parent_id = (
                    channel.parent_id
                    if isinstance(channel, discord.Thread)
                    else channel.id
                )
                if parent_id not in destinations:
                    raise ValueError("An allowed work channel has no webhook.")
            self._destinations = destinations
            return frozenset(channel_ids) or frozenset(
                str(channel_id) for channel_id in destinations
            )

    async def send(
        self,
        task: CharacterWork,
        character: CharacterDefinition,
        text: str,
        attachments: tuple[WorkAttachment, ...],
    ) -> PublishedSpeech:
        """Confirm webhook identity and destination before posting a single report."""
        files: list[discord.File] = []
        try:
            async with asyncio.timeout(30):
                channel = await self._client.fetch_channel(int(task.channel_id))
                if not isinstance(channel, (discord.TextChannel, discord.Thread)) or (
                    task.guild_id != self._guild_id
                    or str(channel.guild.id) != self._guild_id
                ):
                    raise CharacterWorkError("作業の報告先が設定と一致しません。")
                parent_id = (
                    channel.parent_id
                    if isinstance(channel, discord.Thread)
                    else channel.id
                )
                webhook = self._destinations.get(parent_id)
                if webhook is None:
                    raise CharacterWorkError("この作業の報告先Webhookがありません。")
                remote = await webhook.fetch(prefer_auth=False)
                if (
                    str(remote.guild_id) != self._guild_id
                    or remote.channel_id != parent_id
                ):
                    raise CharacterWorkError("Webhookの送信先が変更されています。")
                uploads = list(attachments)
                if len(text) > 1700:
                    uploads.append(
                        WorkAttachment(
                            f"{task.character_id}-report.txt", text.encode("utf-8")
                        )
                    )
                if len(uploads) > 10 or any(
                    len(item.data) > channel.guild.filesize_limit for item in uploads
                ):
                    raise CharacterWorkError(
                        "成果物がDiscordの添付上限を超えています。"
                    )
                files = [
                    discord.File(io.BytesIO(item.data), filename=item.filename)
                    for item in uploads
                ]
                options: dict[str, Any] = {
                    "content": f"作業 {task.id}\n{text[:1700]}",
                    "username": character.display_name,
                    "allowed_mentions": discord.AllowedMentions.none(),
                    "files": files,
                    "wait": True,
                }
                if character.avatar_url is not None:
                    options["avatar_url"] = character.avatar_url
                if isinstance(channel, discord.Thread):
                    options["thread"] = discord.Object(id=channel.id)
                message = await webhook.send(**options)
                if message is None or str(message.channel.id) != task.channel_id:
                    raise CharacterWorkError("報告の送信先を確認できませんでした。")
                return PublishedSpeech(
                    external_message_id=str(message.id),
                    conversation_scope=DiscordConversationScope(
                        guild_id=task.guild_id, channel_id=task.channel_id
                    ),
                    external_sender_id=str(message.author.id),
                    username=character.display_name,
                    content=text,
                    occurred_at=message.created_at,
                    source_message_id=task.last_message_id,
                )
        except (discord.HTTPException, TimeoutError) as error:
            raise CharacterWorkError(
                "Webhook報告を確認できませんでした。成果は保存されています。!work resultで取得できます。"
            ) from error
        finally:
            for file in files:
                file.close()
                file.fp.close()
