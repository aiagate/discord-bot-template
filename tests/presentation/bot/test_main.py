"""Tests for the Discord bot entry point."""

import json
import logging
import os
import subprocess
import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands
from injector import Injector
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.contracts.messages.character_prompt import DiscordMaster
from app.contracts.ports import ICharacterResponseGenerator, ISpeechPublisher
from app.domain.characters import CharacterRoster
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.discord import DiscordWebhookSpeechPublisherRouter
from app.presentation.bot import __main__ as bot_main
from app.presentation.bot.cogs import (
    DiscordResponseDestination,
    DiscordTimesDestination,
)
from app.presentation.bot.cogs.character_work_cog import CharacterWorkCog


def test_configure_logging_writes_to_nested_log_directory(tmp_path: Path) -> None:
    """Configure a UTF-8 file handler without duplicating it."""
    log_path = tmp_path / "nested" / "log"
    root_logger = logging.getLogger()
    previous_level = root_logger.level
    first: logging.FileHandler | None = None

    try:
        first = bot_main.configure_logging(log_path)
        second = bot_main.configure_logging(log_path)
        logger = logging.getLogger("app.presentation.bot.test")
        logger.info("ログ出力の確認")
        first.flush()

        log_file = log_path / bot_main.LOG_FILENAME
        matching_handlers = [
            handler
            for handler in root_logger.handlers
            if isinstance(handler, logging.FileHandler)
            and Path(handler.baseFilename).resolve() == log_file.resolve()
        ]
        assert log_path.is_dir()
        assert log_file.read_text(encoding="utf-8").endswith("ログ出力の確認\n")
        assert first is second
        assert matching_handlers == [first]
    finally:
        if first is not None:
            root_logger.removeHandler(first)
            first.close()
        root_logger.setLevel(previous_level)


def test_webhook_url_list_parses_json_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(
        bot_main.WEBHOOK_URLS_ENV,
        json.dumps([" first-webhook ", "second-webhook"]),
    )
    assert bot_main._load_character_webhook_urls() == (
        "first-webhook",
        "second-webhook",
    )


@pytest.mark.parametrize("configured", ["{}", '[""]', '["same", "same"]'])
def test_webhook_url_list_rejects_invalid_json_configuration(
    monkeypatch: pytest.MonkeyPatch, configured: str
) -> None:
    monkeypatch.setenv(bot_main.WEBHOOK_URLS_ENV, configured)

    with pytest.raises(ValueError):
        bot_main._load_character_webhook_urls()


@pytest.mark.anyio
async def test_bot_closes_character_response_generator(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bot shutdown closes the configured character response generator."""
    bot = bot_main.MyBot()
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    bot._character_response_generator = generator
    base_close = AsyncMock()
    monkeypatch.setattr(commands.Bot, "close", base_close)

    await bot.close()

    generator.aclose.assert_awaited_once_with()
    base_close.assert_awaited_once_with()


@pytest.mark.anyio
@pytest.mark.parametrize("invalid", [False, True])
@pytest.mark.parametrize("shared_webhook", [False, True])
@pytest.mark.parametrize("configured_channels", ["123", ""])
async def test_optional_work_loads_independently_of_gemini(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    invalid: bool,
    shared_webhook: bool,
    configured_channels: str,
) -> None:
    from app.infrastructure.discord import work_reporter

    reporter = MagicMock(spec=work_reporter.DiscordWorkReporter)
    reporter.initialize = AsyncMock(return_value=frozenset({"123"}))
    reporter.webhook_ids = (999,)
    factory = MagicMock(return_value=reporter)
    monkeypatch.setattr(work_reporter, "DiscordWorkReporter", factory)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("CHARACTER_DEFINITIONS_PATH", raising=False)
    monkeypatch.setattr(bot_main, "PROJECT_ROOT", tmp_path / "bot")
    for key, value in {
        "CODEX_WORK_ROOT": "relative" if invalid else str(tmp_path / "work"),
        "CODEX_WORK_GUILD_ID": "456",
        "CODEX_WORK_CHANNEL_IDS": configured_channels,
        "CODEX_WORK_USER_IDS": "2",
        "CODEX_WORK_REPOSITORY": "",
        "CODEX_WORK_WEBHOOK_URLS_JSON": "" if shared_webhook else '["work-webhook"]',
        "DISCORD_CHARACTER_WEBHOOK_URLS_JSON": '["shared-webhook"]',
    }.items():
        monkeypatch.setenv(key, value)
    bot = bot_main.MyBot()
    bot.mediator = MagicMock()
    try:
        await bot.load_cogs()
        assert bot.get_cog("Discord Message Listener") is not None
        assert bot._character_response_generator is None
        assert (bot.get_command("work") is None) == invalid
        work = bot.get_cog("Character Work")
        assert (work is None) == invalid
        if not invalid:
            factory.assert_called_once_with(
                ("shared-webhook" if shared_webhook else "work-webhook",), bot, "456"
            )
            reporter.initialize.assert_awaited_once_with(
                frozenset({"123"}) if configured_channels else frozenset()
            )
            assert isinstance(work, CharacterWorkCog)
            assert work._settings.channel_ids == frozenset({"123"})
            assert bot._work_webhook_ids == (999,)
    finally:
        await bot.close()


def test_non_ai_entrypoints_import_without_loading_ai_settings_or_sdk(
    tmp_path: Path,
) -> None:
    """Use a fresh interpreter so cached modules cannot hide import side effects."""
    invalid = tmp_path / "characters.override.json"
    invalid.write_text("{invalid json", encoding="utf-8")
    environment = dict(os.environ)
    for key in (
        "GEMINI_API_KEY",
        "DISCORD_CHARACTER_WEBHOOK_URLS_JSON",
        "DISCORD_CHARACTER_GUILD_ID",
    ):
        environment.pop(key, None)
    environment.update(
        {
            "CHARACTER_DEFINITIONS_PATH": str(invalid),
            "PYTHON_DOTENV_DISABLED": "1",
            "LINE_CHANNEL_SECRET": "local-test-secret",
            "LINE_CHANNEL_ACCESS_TOKEN": "local-test-token",
            "PYTHONPATH": str(Path(__file__).parents[3] / "src"),
        }
    )
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.container; import app.presentation.bot.__main__; import app.presentation.api.__main__; import app.presentation.line.__main__; assert 'google.genai' not in sys.modules; assert 'openai_codex' not in sys.modules; assert 'app.application.character_settings' not in sys.modules",
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.anyio
@pytest.mark.parametrize(
    "missing",
    [
        "GEMINI_API_KEY",
        "DISCORD_CHARACTER_WEBHOOK_URLS_JSON",
        "DISCORD_CHARACTER_GUILD_ID",
    ],
)
async def test_missing_ai_setting_keeps_all_normal_cogs_available(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, missing: str
) -> None:
    for key in (
        "GEMINI_API_KEY",
        "DISCORD_CHARACTER_WEBHOOK_URLS_JSON",
        "DISCORD_CHARACTER_GUILD_ID",
    ):
        monkeypatch.setenv(
            key, '["configured"]' if key == bot_main.WEBHOOK_URLS_ENV else "configured"
        )
    monkeypatch.delenv(missing)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    monkeypatch.setenv("CHARACTER_DEFINITIONS_PATH", str(invalid))
    bot = bot_main.MyBot()
    bot.mediator = MagicMock()
    add_cog = AsyncMock()
    monkeypatch.setattr(bot, "add_cog", add_cog)
    await bot.load_cogs()
    assert add_cog.await_count == 4
    listener = add_cog.await_args_list[-1].args[0]
    assert listener._destinations == ()
    assert bot._character_response_generator is None


@pytest.mark.anyio
async def test_invalid_ai_settings_disable_only_ai(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    for key, value in (
        ("GEMINI_API_KEY", "private-key"),
        (bot_main.WEBHOOK_URLS_ENV, '["private-webhook"]'),
        ("DISCORD_CHARACTER_GUILD_ID", "456"),
    ):
        monkeypatch.setenv(key, value)
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{", encoding="utf-8")
    monkeypatch.setenv("CHARACTER_DEFINITIONS_PATH", str(invalid))
    bot = bot_main.MyBot()
    bot.mediator = MagicMock()
    add_cog = AsyncMock()
    monkeypatch.setattr(bot, "add_cog", add_cog)
    await bot.load_cogs()
    assert add_cog.await_count == 4
    assert "AI responses disabled during settings" in caplog.text
    assert "private-key" not in caplog.text and "private-webhook" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize(
    "master_id", ["text", "１２３", "0", "0123", "-1", str(2**64), "1" * 21]
)
async def test_invalid_master_id_disables_ai_before_creating_clients(
    monkeypatch: pytest.MonkeyPatch,
    master_id: str,
    caplog: pytest.LogCaptureFixture,
) -> None:
    from google import genai

    monkeypatch.setenv("GEMINI_API_KEY", "local-test-key")
    monkeypatch.setenv(bot_main.WEBHOOK_URLS_ENV, '["local-test-webhook"]')
    monkeypatch.setenv("DISCORD_CHARACTER_GUILD_ID", "456")
    monkeypatch.setenv("DISCORD_CHARACTER_MASTER_USER_ID", master_id)
    client_factory = MagicMock()
    monkeypatch.setattr(genai, "Client", client_factory)
    bot = bot_main.MyBot()

    assert await bot._configure_characters() == ()
    client_factory.assert_not_called()
    assert bot._character_response_generator is None
    assert "AI responses disabled during settings" in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("fails_destination", [False, True])
async def test_ai_resources_are_bound_only_after_destination_validation(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    fails_destination: bool,
) -> None:
    from google import genai

    from app.infrastructure import discord as discord_adapter
    from app.infrastructure import gemini as gemini_adapter

    for key, value in (
        ("GEMINI_API_KEY", "local-test-key"),
        (bot_main.WEBHOOK_URLS_ENV, '["local-test-webhook"]'),
        ("DISCORD_CHARACTER_GUILD_ID", "456"),
    ):
        monkeypatch.setenv(key, value)
    monkeypatch.delenv("CHARACTER_DEFINITIONS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(bot_main, "PROJECT_ROOT", tmp_path)
    (tmp_path / bot_main.MASTER_CONTEXT_FILENAME).write_text(
        "マスターは短い返答を好む。", encoding="utf-8"
    )
    (tmp_path / "characters.override.json").write_text(
        json.dumps(
            {
                "characters": {
                    "Dorothy": {
                        "mcp_servers": {
                            "notes": {
                                "command": "unused-server",
                                "allowed_tools": ["read_note"],
                            }
                        }
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    client_factory = MagicMock()
    monkeypatch.setattr(genai, "Client", client_factory)
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    generator_factory = MagicMock(return_value=generator)
    monkeypatch.setattr(
        gemini_adapter, "GeminiCharacterResponseGenerator", generator_factory
    )
    publisher = AsyncMock(spec=discord_adapter.DiscordWebhookSpeechPublisher)
    publisher.webhook_id = 999
    scope = DiscordConversationScope(guild_id="456", channel_id="123")
    publisher.initialize.return_value = scope
    if fails_destination:
        publisher.initialize.side_effect = ValueError("foreign guild")
    monkeypatch.setattr(
        discord_adapter,
        "DiscordWebhookSpeechPublisher",
        MagicMock(return_value=publisher),
    )
    bot = bot_main.MyBot()
    bot.injector = Injector()
    publisher.is_forum = False
    destinations = await bot._configure_characters()
    if fails_destination:
        assert destinations == ()
        generator.aclose.assert_awaited_once()
        publisher.recover_pending.assert_not_awaited()
        assert bot._character_response_generator is None
        return
    assert destinations == (DiscordResponseDestination(scope, 999, False),)
    assert bot.injector.get(ICharacterResponseGenerator) is generator
    assert bot.injector.get(DiscordMaster).context == "マスターは短い返答を好む。"
    assert isinstance(
        bot.injector.get(ISpeechPublisher), DiscordWebhookSpeechPublisherRouter
    )
    assert bot.injector.get(CharacterRoster).characters
    publisher.recover_pending.assert_awaited_once()
    options = client_factory.call_args.kwargs["http_options"]
    assert options.timeout == 20_000
    assert options.retry_options.attempts == 3
    assert generator_factory.call_args.kwargs["model"] == bot_main.DEFAULT_GEMINI_MODEL
    mcp_servers = generator_factory.call_args.kwargs["mcp_servers"]
    assert set(mcp_servers) == {"Dorothy"}
    assert mcp_servers["Dorothy"][0].allowed_tools == ("read_note",)
    await bot.close()


@pytest.mark.anyio
async def test_configures_multiple_webhook_destinations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    from google import genai

    from app.infrastructure import discord as discord_adapter
    from app.infrastructure import gemini as gemini_adapter

    monkeypatch.setenv("GEMINI_API_KEY", "local-test-key")
    monkeypatch.setenv(
        bot_main.WEBHOOK_URLS_ENV,
        json.dumps(["local-test-webhook", "local-test-discussion-webhook"]),
    )
    monkeypatch.setenv("DISCORD_CHARACTER_GUILD_ID", "456")
    monkeypatch.delenv("CHARACTER_DEFINITIONS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(bot_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(genai, "Client", MagicMock())
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    monkeypatch.setattr(
        gemini_adapter,
        "GeminiCharacterResponseGenerator",
        MagicMock(return_value=generator),
    )
    text_publisher = AsyncMock(spec=discord_adapter.DiscordWebhookSpeechPublisher)
    text_publisher.webhook_id = 999
    text_publisher.is_forum = False
    text_publisher.initialize.return_value = DiscordConversationScope(
        guild_id="456", channel_id="123"
    )
    forum_publisher = AsyncMock(spec=discord_adapter.DiscordWebhookSpeechPublisher)
    forum_publisher.webhook_id = 998
    forum_publisher.is_forum = True
    forum_publisher.initialize.return_value = DiscordConversationScope(
        guild_id="456", channel_id="321"
    )
    publisher_factory = MagicMock(side_effect=[text_publisher, forum_publisher])
    monkeypatch.setattr(
        discord_adapter, "DiscordWebhookSpeechPublisher", publisher_factory
    )
    bot = bot_main.MyBot()
    bot.injector = Injector()

    destinations = await bot._configure_characters()

    assert destinations == (
        DiscordResponseDestination(
            DiscordConversationScope(guild_id="456", channel_id="123"), 999, False
        ),
        DiscordResponseDestination(
            DiscordConversationScope(guild_id="456", channel_id="321"), 998, True
        ),
    )
    assert publisher_factory.call_count == 2
    text_publisher.recover_pending.assert_awaited_once()
    forum_publisher.recover_pending.assert_awaited_once()
    assert isinstance(
        bot.injector.get(ISpeechPublisher), DiscordWebhookSpeechPublisherRouter
    )
    await bot.close()


@pytest.mark.anyio
async def test_bot_closes_discord_client_when_generator_close_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Discord shutdown still runs when generator cleanup raises."""
    bot = bot_main.MyBot()
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    generator.aclose.side_effect = RuntimeError("cleanup failed")
    bot._character_response_generator = generator
    base_close = AsyncMock()
    monkeypatch.setattr(commands.Bot, "close", base_close)

    with pytest.raises(RuntimeError, match="cleanup failed"):
        await bot.close()

    base_close.assert_awaited_once_with()


@pytest.mark.anyio
@pytest.mark.parametrize("fails_times", [False, True])
@pytest.mark.parametrize("master_id", ["", " 672491948375932937 "])
async def test_configures_times_destination_and_validates(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    session_factory: async_sessionmaker[AsyncSession],
    fails_times: bool,
    master_id: str,
) -> None:
    from google import genai

    from app.contracts.ports import (
        ICharacterMemoryStore,
        ITimesEpisodeStore,
        ITimesPublisher,
    )
    from app.infrastructure import discord as discord_adapter
    from app.infrastructure import gemini as gemini_adapter

    monkeypatch.setenv("GEMINI_API_KEY", "local-test-key")
    monkeypatch.setenv(
        bot_main.WEBHOOK_URLS_ENV,
        json.dumps(["local-test-webhook"]),
    )
    monkeypatch.setenv(bot_main.TIMES_WEBHOOK_URL_ENV, "local-test-times-webhook")
    monkeypatch.setenv("DISCORD_CHARACTER_GUILD_ID", "456")
    monkeypatch.setenv("DISCORD_CHARACTER_MASTER_USER_ID", master_id)
    monkeypatch.delenv("CHARACTER_DEFINITIONS_PATH", raising=False)
    monkeypatch.delenv("GEMINI_MODEL", raising=False)
    monkeypatch.setattr(bot_main, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(genai, "Client", MagicMock())
    generator = AsyncMock(spec=ICharacterResponseGenerator)
    monkeypatch.setattr(
        gemini_adapter,
        "GeminiCharacterResponseGenerator",
        MagicMock(return_value=generator),
    )

    char_publisher = AsyncMock(spec=discord_adapter.DiscordWebhookSpeechPublisher)
    char_publisher.webhook_id = 999
    char_publisher.is_forum = False
    char_publisher.initialize.return_value = DiscordConversationScope(
        guild_id="456", channel_id="123"
    )
    char_factory = MagicMock(return_value=char_publisher)
    monkeypatch.setattr(
        discord_adapter,
        "DiscordWebhookSpeechPublisher",
        char_factory,
    )

    times_publisher = AsyncMock(spec=discord_adapter.DiscordWebhookTimesPublisher)
    times_publisher.webhook_id = 888
    times_publisher.initialize.return_value = DiscordConversationScope(
        guild_id="456", channel_id="789"
    )
    if fails_times:
        times_publisher.initialize.side_effect = ValueError(
            "Times webhook destination must not be a character response channel."
        )
    times_factory = MagicMock(return_value=times_publisher)
    monkeypatch.setattr(
        discord_adapter,
        "DiscordWebhookTimesPublisher",
        times_factory,
    )

    bot = bot_main.MyBot()
    bot.injector = Injector()

    memory_store = AsyncMock(spec=ICharacterMemoryStore)
    bot.injector.binder.bind(ICharacterMemoryStore, to=memory_store)

    destinations = await bot._configure_characters()

    master = bot.injector.get(DiscordMaster)
    assert master.user_id == (master_id.strip() or None)
    assert char_factory.call_args.kwargs["master"] is master
    assert times_factory.call_args.kwargs["master"] is master
    assert times_factory.call_args.kwargs["memory_store"] is memory_store

    if fails_times:
        assert destinations == (
            DiscordResponseDestination(
                DiscordConversationScope(guild_id="456", channel_id="123"),
                999,
                False,
            ),
        )
        assert bot._times_destination is None
        assert bot._character_response_generator is generator
        generator.aclose.assert_not_awaited()
        char_publisher.recover_pending.assert_awaited_once()
        times_publisher.recover_pending.assert_not_awaited()
        return

    assert destinations == (
        DiscordResponseDestination(
            DiscordConversationScope(guild_id="456", channel_id="123"), 999, False
        ),
    )
    assert bot._times_destination == DiscordTimesDestination(
        DiscordConversationScope(guild_id="456", channel_id="789"), 888
    )
    assert bot.injector.get(ITimesPublisher) is times_publisher
    assert isinstance(bot.injector.get(ITimesEpisodeStore), ITimesEpisodeStore)
    times_publisher.recover_pending.assert_awaited_once()
    await bot.close()
