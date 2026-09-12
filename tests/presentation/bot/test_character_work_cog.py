"""Discord access, conversation routing, and durable result delivery."""

import asyncio
import io
import zipfile
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from discord.ext import commands
from flow_res import Ok
from openai_codex.generated.v2_all import MessagePhase

from app.application.character_settings import load_ai_maid_definitions
from app.application.character_work_settings import CharacterWorkSettings
from app.contracts.messages.character_work import CharacterWork, WorkAttachment
from app.contracts.messages.speech_message import PublishedSpeech
from app.contracts.ports.character_work import (
    ICharacterWorkExecutor,
    ICharacterWorkReporter,
    ICharacterWorkStore,
)
from app.domain.characters import CharacterDefinition
from app.domain.value_objects import DiscordConversationScope
from app.infrastructure.codex.work_executor import CodexCharacterWorkExecutor
from app.infrastructure.codex.work_store import FileCharacterWorkStore
from app.presentation.bot.cogs.character_work_cog import CharacterWorkCog
from tests.infrastructure.test_codex_work_executor import _client, _completed
from tests.infrastructure.test_codex_work_executor import _message as _codex_message
from tests.infrastructure.test_discord_work_reporter import _reporter
from tests.presentation.bot.test_message_listener_cog import _cog as _listener
from tests.presentation.bot.test_message_listener_cog import _message


def _task() -> CharacterWork:
    return CharacterWork("100", "456", "123", "2", "lilia", "調査", "100")


def _cog(tmp_path: Path) -> tuple[CharacterWorkCog, MagicMock, MagicMock]:
    bot = MagicMock(spec=commands.Bot)
    bot.get_context = AsyncMock(return_value=SimpleNamespace(prefix=None))
    mediator = MagicMock()
    mediator.send_async = AsyncMock(return_value=Ok(None))
    store = AsyncMock(spec=ICharacterWorkStore)
    store.list_tasks.return_value = []
    settings = CharacterWorkSettings(
        tmp_path,
        "456",
        frozenset({"123"}),
        frozenset({"2"}),
    )
    reporter = AsyncMock(spec=ICharacterWorkReporter)

    async def send(
        task: CharacterWork,
        character: CharacterDefinition,
        text: str,
        attachments: tuple[WorkAttachment, ...],
    ) -> PublishedSpeech:
        return PublishedSpeech(
            "200",
            DiscordConversationScope(guild_id="456", channel_id="123"),
            "999",
            character.name,
            text,
            datetime.now(UTC),
            task.last_message_id,
        )

    reporter.send.side_effect = send
    executor = MagicMock(spec=ICharacterWorkExecutor)
    executor.attachments = AsyncMock(
        return_value=(WorkAttachment("source.zip", b"archive"),)
    )
    cog = CharacterWorkCog(
        bot,
        mediator,
        settings,
        load_ai_maid_definitions(),
        store,
        executor,
        reporter,
    )
    cog._service.start = AsyncMock(return_value=Ok(_task()))
    cog._service.follow_up = AsyncMock(return_value=Ok(_task()))
    return cog, bot, mediator


@pytest.mark.anyio
@pytest.mark.parametrize(
    "character",
    load_ai_maid_definitions().characters,
    ids=[item.character_id for item in load_ai_maid_definitions().characters],
)
async def test_named_start_then_ordinary_followup(
    tmp_path: Path,
    character: CharacterDefinition,
) -> None:
    cog, _, _ = _cog(tmp_path)
    start = cog._service.start
    follow = cog._service.follow_up
    assert isinstance(start, AsyncMock) and isinstance(follow, AsyncMock)
    message = _message(content=f"{character.name}、公式資料を調べて")
    assert not await cog.handle_message(message)
    start.assert_awaited_once_with(
        guild_id="456",
        channel_id="123",
        owner_id="2",
        message_id="100",
        character_id=character.character_id,
        prompt="公式資料を調べて",
    )
    cog._service._records["100"] = replace(_task(), character_id=character.character_id)
    assert not await cog.handle_message(_message(101, content="Python版も比較して"))
    follow.assert_awaited_once_with(
        guild_id="456",
        channel_id="123",
        owner_id="2",
        message_id="101",
        prompt="Python版も比較して",
    )
    message.reply.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("scope", ["dm", "guild", "channel", "user", "bot", "webhook"])
async def test_work_is_never_started_outside_allowlist(
    tmp_path: Path, scope: str
) -> None:
    cog, _, _ = _cog(tmp_path)
    message = _message(content="Noa、実装して")
    if scope == "dm":
        message.guild = None
    elif scope == "guild":
        message.guild.id = 789
    elif scope == "channel":
        message.channel.id = 789
    elif scope == "user":
        message.author.id = 789
    elif scope == "bot":
        message.author.bot = True
    else:
        message.webhook_id = 789
    assert not await cog.handle_message(message)
    assert isinstance(cog._service.start, AsyncMock)
    cog._service.start.assert_not_awaited()
    context = MagicMock(spec=commands.Context)
    context.message = message
    assert not cog.cog_check(context)


@pytest.mark.anyio
async def test_threads_in_allowed_parent_and_commands_route_separately(
    tmp_path: Path,
) -> None:
    cog, bot, _ = _cog(tmp_path)
    assert not await cog.handle_message(
        _message(content="lilia 作業: 調査", channel_id=124, parent_id=123)
    )
    bot.get_context.return_value = SimpleNamespace(prefix="!")
    cog._service._records["100"] = _task()
    assert not await cog.handle_message(_message(content="!work stop"))
    assert isinstance(cog._service.follow_up, AsyncMock)
    cog._service.follow_up.assert_not_awaited()


@pytest.mark.anyio
async def test_casual_named_chat_is_left_for_gemini(tmp_path: Path) -> None:
    cog, _, _ = _cog(tmp_path)
    message = _message(content="Lilia、ごめん再設定した。")
    assert not await cog.handle_message(message)
    start = cog._service.start
    assert isinstance(start, AsyncMock)
    start.assert_not_awaited()
    message.reply.assert_not_awaited()


@pytest.mark.anyio
async def test_ordinary_chat_without_link_is_unchanged(tmp_path: Path) -> None:
    cog, _, _ = _cog(tmp_path)
    assert not await cog.handle_message(_message(content="こんにちは"))
    assert not await cog.handle_message(_message(content=""))


@pytest.mark.anyio
async def test_result_upload_is_bounded_and_saved_with_character_identity(
    tmp_path: Path,
) -> None:
    cog, _, mediator = _cog(tmp_path)
    task = replace(_task(), status="completed", result="結果" * 2000)
    await cog._publish(task)
    report = cog._reporter.send
    assert isinstance(report, AsyncMock)
    assert report.await_args is not None
    args = report.await_args.args
    assert args[1].name == "Lilia"
    assert args[1].avatar_url
    assert args[2] == task.result
    assert args[3] == (WorkAttachment("source.zip", b"archive"),)
    mediator.send_async.assert_not_awaited()
    await cog._send(task, "短い結果")
    assert report.await_args is not None
    assert report.await_args.args[3] == ()
    mediator.send_async.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("initial_send_fails", [False, True])
@pytest.mark.parametrize("character_id", ["lilia", "noa", "dorothy", "mira"])
async def test_generated_memo_is_saved_then_attached_and_retrieved_after_restart(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    initial_send_fails: bool,
    character_id: str,
) -> None:
    client, thread, turn = _client(
        monkeypatch,
        [
            _codex_message("出典を確認しました。", MessagePhase.final_answer),
            _completed(),
        ],
    )
    _, bot, mediator = _cog(tmp_path)
    reporter, webhook, _, _ = _reporter(monkeypatch)
    await reporter.initialize(frozenset({"123"}))
    settings = CharacterWorkSettings(
        tmp_path, "456", frozenset({"123"}), frozenset({"2"})
    )
    store = FileCharacterWorkStore(tmp_path / "tasks")
    character = next(
        item
        for item in load_ai_maid_definitions().characters
        if item.character_id == character_id
    )
    generated = tmp_path / "workspaces" / character_id / "100" / "work-report.md"
    original = "調査メモ本体と出典URL".encode()

    async def generate(prompt: str) -> MagicMock:
        generated.write_bytes(original)
        return turn

    thread.turn.side_effect = generate
    delivered: list[dict[str, bytes]] = []

    async def send(**options: Any) -> object:
        if not options["files"]:
            return webhook.send.return_value
        record = (await store.list_tasks())[0]
        assert record.status == "completed" and record.artifacts is not None
        client.close.assert_awaited_once()
        delivered.append({file.filename: file.fp.read() for file in options["files"]})
        if initial_send_fails and len(delivered) == 1:
            raise TimeoutError("uncertain delivery")
        return webhook.send.return_value

    webhook.send.side_effect = send

    def fresh_cog() -> CharacterWorkCog:
        return CharacterWorkCog(
            bot,
            mediator,
            settings,
            load_ai_maid_definitions(),
            FileCharacterWorkStore(tmp_path / "tasks"),
            CodexCharacterWorkExecutor(tmp_path, None),
            reporter,
        )

    cog = fresh_cog()
    await cog.cog_load()
    try:
        assert not await cog.handle_message(
            _message(content=f"{character.name}、調べて")
        )
        async with asyncio.timeout(3):
            await asyncio.gather(*cog._service._active.values())
        record = (await store.list_tasks())[0]
        assert record.status == "completed" and record.artifacts is not None
        assert len(delivered) == 1
        archive_bytes = delivered[0][f"{character_id}-100-100.zip"]
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            assert archive.read("files/work-report.md") == original
        assert "SHA-256" in webhook.send.await_args.kwargs["content"]
        assert webhook.send.await_args.kwargs["username"] == character.display_name
        assert webhook.send.await_args.kwargs["avatar_url"] == character.avatar_url
        assert mediator.send_async.await_count == 0
    finally:
        await cog.cog_unload()

    generated.write_text("later edit")
    restored = fresh_cog()
    await restored.cog_load()
    try:
        context = MagicMock(spec=commands.Context)
        context.message = _message(content="!work result")
        restored.work_result.cog = restored
        await restored.work_result(context)
        assert delivered[1][f"{character_id}-100-100.zip"] == archive_bytes
        thread.turn.assert_awaited_once()
        assert mediator.send_async.await_count == 0
    finally:
        await restored.cog_unload()


@pytest.mark.anyio
@pytest.mark.parametrize("enabled", [False, True])
async def test_listener_routes_work_before_optional_gemini(enabled: bool) -> None:
    listener, save, _ = _listener(enabled=enabled)
    handler = AsyncMock(return_value=True)
    listener._work_handler = handler
    message = _message(content="Lilia、調べて")
    await listener.on_message(message)
    save.assert_awaited_once()
    handler.assert_awaited_once_with(message)
    assert listener._queue.empty()


@pytest.mark.anyio
async def test_work_routing_failure_does_not_fall_through_to_second_agent() -> None:
    listener, _, _ = _listener()
    listener._work_handler = AsyncMock(side_effect=RuntimeError("offline"))
    message = _message(content="Lilia、調べて")
    await listener.on_message(message)
    assert listener._queue.empty()
    assert "状態を確認" in message.reply.await_args.args[0]
