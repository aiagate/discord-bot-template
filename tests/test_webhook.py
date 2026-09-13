"""Character attribution, scoped delivery, and recovery at the Discord boundary."""

import inspect
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import anyio
import discord
import pytest

from app.contracts.messages.support import (
    Character,
    Communication,
    DeliveryAttempt,
    Notice,
    Outcome,
)
from app.infrastructure.store import LocalStore
from app.infrastructure.webhook import DiscordWebhookPublisher
from app.usecases.support import Communicator

URL = "https://discord.com/api/webhooks/900/" + "secret" * 12


@dataclass
class Transport:
    """SDK-shaped test doubles with durable remote messages independent of the host."""

    publisher: DiscordWebhookPublisher
    client: MagicMock
    webhook: MagicMock
    channel: MagicMock
    sent: list[dict[str, Any]]
    messages: list[Any]


@pytest.fixture
def transport(store: LocalStore, monkeypatch: pytest.MonkeyPatch) -> Transport:
    """Keep actual Discord parameter binding and attachment serialization in tests."""
    client = MagicMock(spec=discord.Client)
    channel = MagicMock(spec=discord.TextChannel)
    channel.id = 10
    channel.guild = SimpleNamespace(id=1)
    channel.send = AsyncMock(side_effect=AssertionError("Bot must not send"))
    client.fetch_channel = AsyncMock(return_value=channel)
    webhook = MagicMock(spec=discord.Webhook)
    webhook.id = 900
    webhook.guild_id = 1
    webhook.channel_id = 10
    webhook.type = discord.WebhookType.incoming
    webhook.fetch = AsyncMock(return_value=webhook)
    sent: list[dict[str, Any]] = []
    messages: list[Any] = []

    async def history(**kwargs: Any) -> AsyncIterator[Any]:
        for message in messages:
            yield message

    async def send(**kwargs: Any) -> Any:
        inspect.signature(discord.Webhook.send).bind(webhook, **kwargs)
        files = [file.fp.read() for file in kwargs["files"]]
        sent.append({**kwargs, "file_bytes": files})
        message = SimpleNamespace(
            id=1000 + len(sent),
            channel=channel,
            webhook_id=webhook.id,
            author=SimpleNamespace(display_name=kwargs["username"]),
            content=kwargs["content"],
            embeds=[kwargs["embed"]],
            created_at=datetime.now(UTC),
        )
        messages.append(message)
        return message

    channel.history = history
    webhook.send = AsyncMock(side_effect=send)
    monkeypatch.setattr(discord.Webhook, "from_url", MagicMock(return_value=webhook))
    publisher = DiscordWebhookPublisher(store, client, URL, 10)
    return Transport(publisher, client, webhook, channel, sent, messages)


def notice(
    store: LocalStore, character_id: str = "noa", text: str = "確認しました。"
) -> Notice:
    """Queue a real autonomous result without requiring a human message ID."""
    store.create("目的", ("条件",), "範囲", character_id, now=1)
    activity = store.claim(1)
    assert activity is not None
    store.finish(
        activity,
        Outcome(
            action="complete",
            summary="内部記録",
            rationale="条件を確認した",
            next_step="",
            evidence=("確認記録",),
            achieved=(0,),
            communication=Communication(content=text),
        ),
        2,
    )
    return store.pending_notices()[-1]


@pytest.mark.anyio
async def test_characters_and_controls_share_one_webhook(
    store: LocalStore,
    transport: Transport,
) -> None:
    """Autonomous notices and fixed control replies use each captured character."""
    first = notice(store)
    second = notice(store, "astra")
    character_path = store.root / "characters/noa.json"
    character_path.write_text(
        store.character("noa")
        .model_copy(update={"avatar_url": "https://example.invalid/noa.png"})
        .model_dump_json()
    )
    store.command(second.activity_id, "!status", "discord:command")
    await transport.publisher.initialize()
    original_send = transport.webhook.send.side_effect

    async def observed_text(**kwargs: Any) -> Any:
        message = await original_send(**kwargs)
        message.content = "\n" + message.content + "\n"
        return message

    transport.webhook.send.side_effect = observed_text
    speaker = MagicMock()

    def render(notice: Notice, character: Character) -> str:
        return notice.content

    speaker.render = AsyncMock(side_effect=render)
    assert await Communicator(store, transport.publisher, speaker).flush() == 3
    assert [item["username"] for item in transport.sent] == ["Noa", "Astra", "Astra"]
    assert transport.sent[0]["avatar_url"] == "https://example.invalid/noa.png"
    assert "avatar_url" not in transport.sent[1]
    assert all(item["wait"] for item in transport.sent)
    assert speaker.render.await_count == 2
    assert not store.pending_notices()
    event = store.continuity(first.activity_id).last_delivery
    assert event is not None and event.delivery is not None
    assert event.delivery.message_id == "1001"
    assert event.delivery.sender_id == "900"
    assert event.delivery.content == transport.messages[0].content
    assert event.delivery.content.startswith("\n")
    assert (
        "secret"
        not in store.context(store.current(first.activity_id), 3).model_dump_json()
    )


@pytest.mark.anyio
async def test_long_content_preserves_unicode_and_closes_attachments(
    store: LocalStore,
    transport: Transport,
) -> None:
    """The displayed excerpt stays valid and the complete message remains attached."""
    pending = notice(store, text="🌟" * 2500 + " @everyone")
    await transport.publisher.initialize()
    assert await Communicator(store, transport.publisher).flush() == 1
    item = transport.sent[0]
    assert len(item["content"].encode("utf-16-le")) <= 4000
    assert item["file_bytes"][0].decode() == pending.content
    assert item["allowed_mentions"].everyone is False
    assert item["allowed_mentions"].users is False
    assert item["files"][0].fp.closed


@pytest.mark.anyio
@pytest.mark.parametrize("failure", ["receipt_save", "after_send", "before_mark"])
async def test_restart_confirms_sent_message_without_resending(
    store: LocalStore,
    transport: Transport,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """Recovery uses durable receipts or remote history after each interruption point."""
    pending = notice(store)
    await transport.publisher.initialize()
    save = store.save_discord_attempt
    original_send = transport.webhook.send.side_effect
    if failure == "receipt_save":

        def fail_receipt(notice_id: str, attempt: DeliveryAttempt) -> None:
            if attempt.receipt is not None:
                raise OSError("disk")
            save(notice_id, attempt)

        monkeypatch.setattr(store, "save_discord_attempt", fail_receipt)
    elif failure == "after_send":

        async def fail_response(**kwargs: Any) -> None:
            await original_send(**kwargs)
            raise TimeoutError("connection lost")

        transport.webhook.send.side_effect = fail_response
    if failure == "before_mark":
        await transport.publisher.send(pending, store.character("noa"))
    else:
        assert await Communicator(store, transport.publisher).flush() == 0
    reopened = LocalStore(store.root)
    publisher = DiscordWebhookPublisher(reopened, transport.client, URL, 10)
    await publisher.initialize()
    assert await Communicator(reopened, publisher).flush() == 1
    assert len(transport.sent) == 1
    assert not reopened.pending_notices()


@pytest.mark.anyio
async def test_unconfirmed_send_does_not_repeat_or_block_other_notices(
    store: LocalStore,
    transport: Transport,
) -> None:
    """A missing remote confirmation is not evidence that resending is safe."""
    first = notice(store)
    second = notice(store, "astra")
    store.save_discord_attempt(first.id, DeliveryAttempt(started_at=1))
    await transport.publisher.initialize()
    assert await Communicator(store, transport.publisher).flush() == 1
    assert [item.id for item in store.pending_notices()] == [first.id]
    assert len(transport.sent) == 1
    assert transport.sent[0]["embed"].footer.text == f"support:{second.id}"
    assert await Communicator(store, transport.publisher).flush() == 0
    assert len(transport.sent) == 1


@pytest.mark.anyio
async def test_definite_rejection_can_retry_after_correction(
    store: LocalStore,
    transport: Transport,
) -> None:
    """A rejected request can be retried without treating it as an unknown send."""
    pending = notice(store)
    await transport.publisher.initialize()
    send = transport.webhook.send.side_effect
    transport.webhook.send.side_effect = discord.Forbidden(
        MagicMock(status=403, reason="Forbidden"), "denied"
    )
    assert await Communicator(store, transport.publisher).flush() == 0
    assert store.discord_attempt(pending.id) is None
    transport.webhook.send.side_effect = send
    assert await Communicator(store, transport.publisher).flush() == 1


@pytest.mark.anyio
@pytest.mark.parametrize(
    "field,value", [("guild_id", 2), ("channel_id", 11), ("id", 901)]
)
async def test_wrong_or_moved_destination_is_never_used(
    store: LocalStore,
    transport: Transport,
    field: str,
    value: int,
) -> None:
    """Startup and every new send validate the destination against the saved window."""
    notice(store)
    await transport.publisher.initialize()
    remote = SimpleNamespace(
        id=900, guild_id=1, channel_id=10, type=discord.WebhookType.incoming
    )
    setattr(remote, field, value)
    transport.webhook.fetch.return_value = remote
    assert await Communicator(store, transport.publisher).flush() == 0
    assert not transport.sent
    publisher = DiscordWebhookPublisher(store, transport.client, URL, 10)
    with pytest.raises(ValueError, match="送信先"):
        await publisher.initialize()
    assert (
        next(f for f in store.runtime() if f.component == "webhook").status == "failure"
    )


@pytest.mark.anyio
async def test_bound_window_cannot_change_on_restart(
    store: LocalStore,
    transport: Transport,
) -> None:
    """A valid alternative window cannot receive the original window's queued notices."""
    await transport.publisher.initialize()
    transport.channel.id = 11
    transport.webhook.channel_id = 11
    publisher = DiscordWebhookPublisher(
        LocalStore(store.root), transport.client, URL, 11
    )
    with pytest.raises(ValueError, match="送信先"):
        await publisher.initialize()
    destination = store.discord_destination()
    assert destination is not None and destination.channel_id == 10


@pytest.mark.anyio
async def test_thread_delivery_keeps_its_parent_and_actual_thread(
    store: LocalStore,
    transport: Transport,
) -> None:
    """A parent webhook speaks into the designated thread, not the parent channel."""
    pending = notice(store)
    thread = MagicMock(spec=discord.Thread)
    thread.id = 12
    thread.parent_id = 10
    thread.guild = transport.channel.guild

    def channel(channel_id: int) -> MagicMock:
        return thread if channel_id == 12 else transport.channel

    transport.client.fetch_channel.side_effect = channel
    original_send = transport.webhook.send.side_effect

    async def send(**kwargs: Any) -> Any:
        message = await original_send(**kwargs)
        message.channel = thread
        return message

    transport.webhook.send.side_effect = send
    publisher = DiscordWebhookPublisher(store, transport.client, URL, 12)
    await publisher.initialize()
    receipt = await publisher.send(pending, store.character("noa"))
    assert receipt.channel_id == "12"
    assert transport.sent[0]["thread"].id == 12
    thread.parent_id = 13

    def moved(channel_id: int) -> MagicMock:
        return (
            thread
            if channel_id == 12
            else MagicMock(spec=discord.TextChannel, id=13, guild=thread.guild)
        )

    transport.client.fetch_channel.side_effect = moved
    with pytest.raises(ValueError):
        await publisher.initialize()


def test_invalid_url_does_not_disclose_credentials(store: LocalStore) -> None:
    """Configuration errors never echo the secret-bearing URL."""
    with pytest.raises(ValueError) as error:
        DiscordWebhookPublisher(
            store, MagicMock(spec=discord.Client), "private-secret", 10
        )
    assert "private-secret" not in str(error.value)


@pytest.mark.anyio
async def test_cancelled_send_keeps_attempt_and_releases_files(
    store: LocalStore,
    transport: Transport,
) -> None:
    """A cancelled request can be confirmed after restart without uploading twice."""
    pending = notice(store, text="x" * 3000)
    await transport.publisher.initialize()
    original = transport.webhook.send.side_effect

    async def interrupted(**kwargs: Any) -> None:
        await original(**kwargs)
        raise anyio.get_cancelled_exc_class()()

    transport.webhook.send.side_effect = interrupted
    with pytest.raises(anyio.get_cancelled_exc_class()):
        await transport.publisher.send(pending, store.character("noa"))
    attempt = store.discord_attempt(pending.id)
    assert attempt is not None and attempt.receipt is None
    assert transport.sent[0]["files"][0].fp.closed
    assert await Communicator(store, transport.publisher).flush() == 1
    assert len(transport.sent) == 1


@pytest.mark.anyio
async def test_remote_errors_do_not_expose_webhook_url_in_logs(
    store: LocalStore,
    transport: Transport,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SDK errors containing request URLs stay inside the transport adapter."""
    notice(store)
    await transport.publisher.initialize()
    transport.webhook.send.side_effect = OSError(URL)
    assert await Communicator(store, transport.publisher).flush() == 0
    assert "secret" not in caplog.text


@pytest.mark.anyio
@pytest.mark.parametrize("valid", [True, False])
async def test_discord_startup_validates_before_accepting_or_running(
    store: LocalStore,
    transport: Transport,
    monkeypatch: pytest.MonkeyPatch,
    valid: bool,
) -> None:
    """The real composition path only starts loops after login and destination binding."""
    from app import cli
    from app.infrastructure.discord import DiscordGateway

    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)
    order: list[str] = []
    connected = anyio.Event()
    serving = anyio.Event()

    def no_speaker() -> None:
        return None

    thinker = MagicMock()
    thinker.close = AsyncMock()

    def conversation() -> Any:
        return thinker

    async def login(self: DiscordGateway, token: str) -> None:
        order.append("login")

    def from_url(url: str, *, client: discord.Client) -> MagicMock:
        assert order == ["login"]
        return transport.webhook

    async def connect(self: DiscordGateway, *, reconnect: bool) -> None:
        assert store.discord_destination() is not None
        order.append("connect")
        connected.set()
        await anyio.sleep_forever()

    async def serve(*args: Any, **kwargs: Any) -> None:
        assert store.discord_destination() is not None
        assert isinstance(args[1].publisher, DiscordWebhookPublisher)
        order.append("serve")
        serving.set()
        await anyio.sleep_forever()

    monkeypatch.setattr(cli, "make_speaker", no_speaker)
    monkeypatch.setattr(cli, "make_conversation_thinker", conversation)
    monkeypatch.setattr(cli, "serve", serve)
    monkeypatch.setattr(DiscordGateway, "login", login)
    monkeypatch.setattr(discord.Webhook, "from_url", from_url)
    monkeypatch.setattr(DiscordGateway, "connect", connect)
    monkeypatch.setattr(
        DiscordGateway, "fetch_channel", AsyncMock(return_value=transport.channel)
    )
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "bot-token")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", URL)
    args = cli.parser().parse_args(
        [
            "discord",
            "--activity",
            activity.id,
            "--channel-id",
            "10",
            "--master-id",
            "20",
        ]
    )
    if valid:
        with anyio.fail_after(2):
            async with anyio.create_task_group() as group:
                group.start_soon(cli.run, store, args)
                await connected.wait()
                await serving.wait()
                group.cancel_scope.cancel()
        assert order[0] == "login"
        assert set(order[1:]) == {"connect", "serve"}
    else:
        transport.webhook.guild_id = 2
        with pytest.raises(ValueError, match="送信先"):
            await cli.run(store, args)
        assert order == ["login"]
    assert store.current(activity.id).runs == 0
    assert not transport.sent
    thinker.close.assert_awaited_once()


@pytest.mark.anyio
async def test_bound_discord_window_cannot_drain_through_local_run(
    store: LocalStore,
    transport: Transport,
) -> None:
    """A CLI mode change cannot silently consume pending Discord speech locally."""
    from app import cli

    pending = notice(store)
    await transport.publisher.initialize()
    with pytest.raises(ValueError, match="Discord"):
        await cli.run(store, cli.parser().parse_args(["run", "--once"]))
    assert store.pending_notices()[0].id == pending.id
