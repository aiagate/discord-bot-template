"""Exercise character identity, attachments, routing, and webhook failures."""

from dataclasses import replace
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import discord
import pytest

from app.application.character_settings import load_ai_maid_definitions
from app.contracts.messages.character_work import (
    CharacterWork,
    CharacterWorkError,
    WorkAttachment,
)
from app.domain.characters import CharacterDefinition
from app.infrastructure.discord.work_reporter import DiscordWorkReporter


def _character(character_id: str = "lilia") -> CharacterDefinition:
    return next(
        character
        for character in load_ai_maid_definitions().characters
        if character.character_id == character_id
    )


def _reporter(
    monkeypatch: pytest.MonkeyPatch,
    *,
    thread: bool = False,
    forum: bool = False,
) -> tuple[DiscordWorkReporter, MagicMock, MagicMock, MagicMock]:
    parent = MagicMock(spec=discord.ForumChannel if forum else discord.TextChannel)
    parent.id = 123
    parent.guild = SimpleNamespace(id=456, filesize_limit=8 * 1024 * 1024)
    channel = MagicMock(spec=discord.Thread) if thread else parent
    if thread:
        channel.id = 124
        channel.parent_id = parent.id
        channel.guild = parent.guild
    webhook = MagicMock(spec=discord.Webhook)
    webhook.id = 999
    webhook.fetch = AsyncMock(
        return_value=SimpleNamespace(guild_id=456, channel_id=123)
    )
    webhook.send = AsyncMock(
        return_value=SimpleNamespace(
            id=200,
            channel=channel,
            author=SimpleNamespace(id=999),
            created_at=datetime(2026, 9, 12, tzinfo=UTC),
        )
    )
    client = MagicMock(spec=discord.Client)

    async def fetch_channel(identifier: int) -> MagicMock:
        return parent if identifier == 123 else channel

    client.fetch_channel = AsyncMock(side_effect=fetch_channel)
    monkeypatch.setattr(discord.Webhook, "from_url", MagicMock(return_value=webhook))
    return DiscordWorkReporter(("test-url",), client, "456"), webhook, client, channel


@pytest.mark.anyio
@pytest.mark.parametrize("character_id", ["lilia", "noa"])
@pytest.mark.parametrize("destination", ["text", "thread", "forum_thread"])
async def test_name_avatar_actual_attachment_and_receipt(
    monkeypatch: pytest.MonkeyPatch,
    character_id: str,
    destination: str,
) -> None:
    reporter, webhook, _, channel = _reporter(
        monkeypatch, thread=destination != "text", forum=destination == "forum_thread"
    )
    await reporter.initialize(frozenset({str(channel.id)}))
    character = _character(character_id)
    task = CharacterWork(
        "100", "456", str(channel.id), "2", character_id, "作業", "101"
    )
    captured: dict[str, bytes] = {}

    async def send(**options: Any) -> object:
        for file in options["files"]:
            captured[file.filename] = file.fp.read()
        return webhook.send.return_value

    webhook.send.side_effect = send
    text = "調査結果 @everyone\n" * 200
    result = await reporter.send(
        task, character, text, (WorkAttachment("code.zip", b"ZIP"),)
    )
    options = webhook.send.await_args.kwargs
    assert options["username"] == character.name
    assert options["avatar_url"] == character.avatar_url
    assert options["wait"] is True
    assert options["allowed_mentions"].to_dict() == {"parse": []}
    assert len(options["content"]) < 2000
    assert captured == {"code.zip": b"ZIP", f"{character_id}-report.txt": text.encode()}
    assert all(file.fp.closed for file in options["files"])
    if destination != "text":
        assert options["thread"].id == channel.id
    else:
        assert "thread" not in options
    assert reporter.webhook_ids == (999,)
    assert result.external_sender_id == "999"
    assert result.external_message_id == "200"
    assert result.source_message_id == "101"
    assert result.conversation_scope.channel_id == str(channel.id)
    assert result.content == text and result.username == character.name


@pytest.mark.anyio
async def test_no_avatar_uses_webhook_default(monkeypatch: pytest.MonkeyPatch) -> None:
    reporter, webhook, _, _ = _reporter(monkeypatch)
    await reporter.initialize(frozenset({"123"}))
    task = CharacterWork("100", "456", "123", "2", "lilia", "作業", "100")
    await reporter.send(task, replace(_character(), avatar_url=None), "進捗", ())
    assert "avatar_url" not in webhook.send.await_args.kwargs
    assert webhook.send.await_args.kwargs["files"] == []


@pytest.mark.anyio
@pytest.mark.parametrize(
    "problem", ["guild", "parent_type", "duplicate", "missing_route", "channel_guild"]
)
async def test_initialization_rejects_invalid_routes(
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    reporter, webhook, client, channel = _reporter(monkeypatch)
    if problem == "guild":
        webhook.fetch.return_value.guild_id = 457
    elif problem == "parent_type":
        client.fetch_channel.return_value = MagicMock(spec=discord.VoiceChannel)
        client.fetch_channel.side_effect = None
    elif problem == "duplicate":
        reporter = DiscordWorkReporter(("first", "second"), client, "456")
    elif problem == "missing_route":
        channel.id = 124
    else:
        channel.guild.id = 457
    with pytest.raises(ValueError):
        await reporter.initialize(frozenset({str(channel.id)}))
    webhook.send.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize(
    "problem",
    ["moved", "task_guild", "channel_guild", "too_large", "too_many", "missing_route"],
)
async def test_delivery_validation_happens_before_send(
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    reporter, webhook, _, channel = _reporter(monkeypatch)
    await reporter.initialize(frozenset({"123"}))
    task = CharacterWork("100", "456", "123", "2", "lilia", "作業", "100")
    attachments = (WorkAttachment("code.zip", b"ZIP"),)
    if problem == "moved":
        webhook.fetch.return_value.channel_id = 124
    elif problem == "task_guild":
        task = replace(task, guild_id="457")
    elif problem == "channel_guild":
        channel.guild.id = 457
    elif problem == "too_large":
        channel.guild.filesize_limit = 2
    elif problem == "too_many":
        attachments *= 11
    else:
        channel.id = 124
    with pytest.raises(CharacterWorkError):
        await reporter.send(task, _character(), "done", attachments)
    webhook.send.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("problem", ["timeout", "http", "no_ack", "wrong_channel"])
async def test_ambiguous_delivery_never_retries_and_closes_files(
    monkeypatch: pytest.MonkeyPatch,
    problem: str,
) -> None:
    reporter, webhook, _, _ = _reporter(monkeypatch)
    await reporter.initialize(frozenset({"123"}))
    task = CharacterWork("100", "456", "123", "2", "lilia", "作業", "100")
    if problem == "timeout":
        webhook.send.side_effect = TimeoutError("test timeout")
    elif problem == "http":
        webhook.send.side_effect = discord.HTTPException(
            MagicMock(status=503, reason="Unavailable"), "test error"
        )
    elif problem == "no_ack":
        webhook.send.return_value = None
    else:
        webhook.send.return_value = SimpleNamespace(channel=SimpleNamespace(id=789))
    with pytest.raises(CharacterWorkError):
        await reporter.send(
            task, _character(), "done", (WorkAttachment("code.zip", b"ZIP"),)
        )
    webhook.send.assert_awaited_once()
    assert all(file.fp.closed for file in webhook.send.await_args.kwargs["files"])


def test_empty_or_invalid_url_does_not_disclose_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with pytest.raises(ValueError, match="Configure"):
        DiscordWorkReporter((), MagicMock(), "456")
    monkeypatch.setattr(
        discord.Webhook, "from_url", MagicMock(side_effect=ValueError("secret-url"))
    )
    with pytest.raises(ValueError, match="Invalid character") as error:
        DiscordWorkReporter(("secret-url",), MagicMock(), "456")
    assert "secret-url" not in str(error.value)
