"""Discord input ownership, control, attribution, and delivery retries."""

from types import SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock

import discord
import pytest

from app.contracts.messages.support import Outcome
from app.infrastructure.discord import DiscordGateway
from app.infrastructure.store import LocalStore


@pytest.mark.anyio
async def test_discord_preserves_master_input_and_rejects_other_actors(
    store: LocalStore,
) -> None:
    """U7: users, bots, and other channels cannot steer this master's work."""
    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)
    gateway = DiscordGateway(store, activity.id, 10, 20)

    async def message(
        content: str,
        *,
        user: int = 20,
        channel: int = 10,
        bot: bool = False,
        webhook: int | None = None,
        message_id: int = 1,
    ) -> AsyncMock:
        reply = AsyncMock()
        value = SimpleNamespace(
            content=content,
            author=SimpleNamespace(id=user, bot=bot),
            channel=SimpleNamespace(id=channel),
            webhook_id=webhook,
            id=message_id,
            reply=reply,
        )
        await gateway.on_message(cast(discord.Message, value))
        reply.assert_not_awaited()
        return reply

    await message("!stop", user=21)
    await message("!stop", channel=11)
    await message("!stop", bot=True)
    await message("!stop", webhook=1)
    assert store.current(activity.id).status == "ready"
    await message("  原文\n")
    await message("  原文\n")
    assert (
        len(
            [
                event
                for event in store.events(activity.id)
                if event.kind == "conversation_input"
            ]
        )
        == 1
    )
    assert store.events(activity.id)[-1].content == "  原文\n"
    assert store.current(activity.id) == activity
    assert store.pending_conversation() is not None
    await message("!stop", message_id=2)
    assert store.current(activity.id).status == "stopped"
    await message("!status", message_id=3)
    assert "停止" in store.pending_notices()[-1].content
    await message("!resume", message_id=4)
    assert store.current(activity.id).status == "ready"
    await message(" ")
    await gateway.close()


def test_commands_survive_restart_and_do_not_repeat_state_changes(
    store: LocalStore,
) -> None:
    """A retried command keeps one state transition and one fixed reply."""
    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)
    store.command(activity.id, "!stop", "discord:1")
    stopped = store.current(activity.id)
    reopened = LocalStore(store.root)
    reopened.command(activity.id, "!stop", "discord:1")
    assert reopened.current(activity.id) == stopped
    (notice,) = reopened.pending_notices()
    assert notice.rendered == notice.content
    assert notice.character_id == "noa"
    reopened.command(activity.id, "!status", "discord:2")
    assert reopened.current(activity.id) == stopped
    reopened.command(activity.id, "!resume", "discord:3")
    assert reopened.current(activity.id).status == "ready"
    with pytest.raises(ValueError):
        reopened.command(activity.id, "!invalid", "discord:4")


def test_command_failure_rolls_back_control_and_original_input(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A failed reply save leaves the command eligible for a complete retry."""
    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)

    def fail(*args: object, **kwargs: object) -> None:
        raise OSError("disk")

    monkeypatch.setattr(store, "_notice", fail)
    with pytest.raises(OSError):
        store.command(activity.id, "!stop", "discord:1")
    assert store.current(activity.id) == activity
    assert not any(event.kind == "command" for event in store.events(activity.id))


def test_status_reply_retains_a_maximum_length_next_step(store: LocalStore) -> None:
    """A long next step cannot prevent the fixed status reply from being saved."""
    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)
    store.finish(
        activity,
        Outcome(
            action="continue",
            summary="調査",
            rationale="続きがある",
            next_step="続" * 12000,
        ),
        2,
    )
    store.command(activity.id, "!status", "discord:1")
    (notice,) = store.pending_notices()
    assert notice.rendered is not None and "続" * 12000 in notice.rendered
