"""One authenticated master speaks naturally; webhooks never become new inputs."""

from datetime import UTC, datetime
from pathlib import Path
from typing import cast
from unittest.mock import AsyncMock, MagicMock

import aiohttp
import anyio
import discord
import pytest
from discord.ext import commands

from app.application.collective_settings import (
    BotCollectiveConfig,
    initialize_characters,
    load_characters,
)
from app.contracts.messages.collective import Speech
from app.presentation.bot.cogs.collective_cog import CollectiveCog
from app.usecases.collective.runtime import Collective
from tests.collective.conftest import ConversationDouble
from tests.collective.test_adapters import Response


def make_cog(collective: Collective) -> CollectiveCog:
    """Attach the real application behind a disconnected Discord cog."""
    config = BotCollectiveConfig(
        root=collective.root,
        guild_id=1,
        master_id=2,
        master_channel_id=3,
        times_channel_id=4,
        agy_skill=Path("/skill"),
    )
    cog = CollectiveCog(cast(commands.Bot, MagicMock(spec=commands.Bot)), config)
    cog.collective = collective
    return cog


def message() -> discord.Message:
    """Construct an unmentioned ordinary message."""
    value = MagicMock(spec=discord.Message)
    value.author = MagicMock(id=2, bot=False)
    value.guild = MagicMock(id=1)
    value.channel = MagicMock(id=3)
    value.id = 5
    value.webhook_id = None
    value.content = "こんにちは、Alice。"
    value.created_at = datetime.now(UTC)
    value.jump_url = "https://discord.com/channels/1/3/5"
    return cast(discord.Message, value)


@pytest.mark.anyio
async def test_normal_unmentioned_master_message_is_accepted_once(
    collective: Collective,
) -> None:
    cog = make_cog(collective)
    incoming = message()
    await cog.on_message(incoming)
    await cog.on_message(incoming)
    turns = collective.store.read().turns
    assert len(turns) == 1
    assert next(iter(turns.values())).character_id == "alice"


@pytest.mark.anyio
@pytest.mark.parametrize(
    "change",
    [
        "bot",
        "webhook",
        "other-user",
        "other-guild",
        "other-channel",
        "dm",
        "management",
    ],
)
async def test_untrusted_or_reflected_inputs_are_ignored(
    collective: Collective, change: str
) -> None:
    cog = make_cog(collective)
    incoming = message()
    if change == "bot":
        incoming.author = MagicMock(id=2, bot=True)
    elif change == "webhook":
        incoming.webhook_id = 10
    elif change == "other-user":
        incoming.author = MagicMock(id=99, bot=False)
    elif change == "other-guild":
        incoming.guild = MagicMock(id=99)
    elif change == "other-channel":
        incoming.channel = MagicMock(id=99)
    elif change == "dm":
        incoming.guild = None
    else:
        incoming.content = "!maid stop activity"
    await cog.on_message(incoming)
    assert not collective.store.read().events


def test_profiles_initialize_without_overwriting_and_validate_identity(
    tmp_path: Path,
) -> None:
    initialize_characters(tmp_path)
    characters = load_characters(tmp_path)
    assert len(characters) == 10
    path = tmp_path / "characters" / "dorothy.json"
    before = path.read_text()
    initialize_characters(tmp_path)
    assert path.read_text() == before
    path.rename(path.with_name("other.json"))
    with pytest.raises(ValueError, match="filenames"):
        load_characters(tmp_path)
    with pytest.raises(ValueError, match="No character"):
        load_characters(tmp_path / "missing")


def test_configuration_requires_distinct_scopes(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="distinct"):
        BotCollectiveConfig(
            root=tmp_path,
            guild_id=1,
            master_id=2,
            master_channel_id=3,
            times_channel_id=3,
            agy_skill=Path("/skill"),
        )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "master_webhook,pool,valid",
    [
        ("https://discord.com/api/webhooks/1/token", "invalid-unused-pool", True),
        (None, '["https://discord.com/api/webhooks/1/token"]', True),
        (None, "must-not-log-this-secret", False),
        (None, '"must-not-log-this-secret"', False),
        (None, "[]", False),
        (None, "{}", False),
        (None, "[null]", False),
        (None, '[""]', False),
    ],
)
async def test_startup_model_outage_does_not_block_saved_delivery(
    collective: Collective,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    master_webhook: str | None,
    pool: str,
    valid: bool,
) -> None:
    cog = make_cog(collective)
    cog.collective = None
    collective.root.joinpath("master.md").write_text("Master policy")
    with collective.store.transaction() as state:
        state.speeches["saved"] = Speech(
            id="saved",
            character_id="alice",
            scope="master",
            origin="saved",
            body="確認できた成果です。",
            status="ready",
        )
    bot = cast(MagicMock, cog.bot)
    bot.wait_until_ready = AsyncMock()
    bot.intents = discord.Intents.all()
    channel = MagicMock(spec=discord.TextChannel)
    channel.guild = MagicMock(id=1)
    channel.permissions_for.return_value = MagicMock(
        view_channel=True, read_message_history=True
    )
    bot.get_channel.return_value = channel
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.side_effect = [
        Response(200, {"id": "1", "channel_id": "3"}),
        Response(200, {"id": "2", "channel_id": "4"}),
    ]
    session.post.return_value = Response(200, {"id": "123"})
    session.close = AsyncMock()
    conversation = ConversationDouble()
    conversation.limits = AsyncMock(side_effect=RuntimeError("Provider unavailable"))
    monkeypatch.setenv("GEMINI_API_KEY", "test")
    if master_webhook is None:
        monkeypatch.delenv("MAID_MASTER_WEBHOOK_URL", raising=False)
    else:
        monkeypatch.setenv("MAID_MASTER_WEBHOOK_URL", master_webhook)
    monkeypatch.setenv("DISCORD_CHARACTER_WEBHOOK_URLS_JSON", pool)
    monkeypatch.setenv(
        "MAID_TIMES_WEBHOOK_URL", "https://discord.com/api/webhooks/2/token"
    )
    monkeypatch.setattr(
        "app.presentation.bot.cogs.collective_cog.aiohttp.ClientSession",
        MagicMock(return_value=session),
    )
    monkeypatch.setattr(
        "app.presentation.bot.cogs.collective_cog.load_characters",
        MagicMock(return_value=collective.characters),
    )
    monkeypatch.setattr(
        "app.presentation.bot.cogs.collective_cog.GeminiConversation",
        MagicMock(return_value=conversation),
    )
    monkeypatch.setattr(
        "app.presentation.bot.cogs.collective_cog.CodexWorker",
        MagicMock(return_value=collective.codex),
    )
    try:
        await cog._start()
        if not valid:
            assert cog.collective is None
            session.get.assert_not_called()
            session.close.assert_awaited_once()
            assert "must-not-log-this-secret" not in caplog.text
            return
        assert cog.collective is not None
        assert (
            session.get.call_args_list[0].args[0]
            == "https://discord.com/api/webhooks/1/token"
        )
        with anyio.fail_after(2):
            while collective.store.read().speeches["saved"].status != "sent":
                await anyio.sleep(0.01)
        session.post.assert_called_once()
        session.close.assert_not_awaited()
    finally:
        await cog.cog_unload()
