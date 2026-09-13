"""Observed runtime facts remain separate from work and model inferences."""

import pytest

from app import cli
from app.contracts.messages.support import (
    Character,
    Communication,
    Notice,
    Outcome,
    RuntimeObservation,
)
from app.infrastructure.communication import FilePublisher
from app.infrastructure.discord import DiscordGateway
from app.infrastructure.store import LocalStore
from app.usecases.support import Communicator


@pytest.mark.anyio
async def test_configuration_is_observed_as_presence_without_credentials(
    store: LocalStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A configured runtime can report its settings to a worker without its keys."""
    for variable in ("COLLECTIVE_GEMINI_MODEL", "COLLECTIVE_CONVERSATION_MODEL"):
        monkeypatch.delenv(variable, raising=False)
    monkeypatch.setenv("GEMINI_API_KEY", "private-gemini-key")
    monkeypatch.setenv("OPENAI_API_KEY", "private-openai-key")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "private-discord-key")
    assert all(
        fact.status == "unknown" and fact.observed_at is None
        for fact in store.runtime()
    )
    await cli.run(store, cli.parser().parse_args(["run", "--once"]))
    activity = store.create("確認", ("状態を確認",), "読み取り", "noa", now=1)
    context = store.context(activity, 1)
    config = next(fact for fact in context.runtime if fact.component == "configuration")
    assert config.status == "configured"
    assert config.settings["gemini_credentials"]
    assert config.settings["openai_credentials"]
    assert config.settings["discord_credentials"]
    assert not config.settings["discord_enabled"]
    assert "private-" not in context.model_dump_json()
    assert (
        next(fact for fact in context.runtime if fact.component == "discord").status
        == "unknown"
    )


@pytest.mark.anyio
async def test_gateway_observations_survive_restart_without_waking_work(
    store: LocalStore,
) -> None:
    """Connection events are timestamped facts, not new work or authentication claims."""
    activity = store.create("確認", ("状態を確認",), "読み取り", "noa", now=1)
    gateway = DiscordGateway(store, activity.id, 1, 2)
    try:
        await gateway.on_ready()
        await gateway.on_disconnect()
        fact = next(
            item
            for item in LocalStore(store.root).runtime()
            if item.component == "discord"
        )
        assert fact.status == "disconnected"
        assert fact.observed_at is not None
        assert fact.source == "DiscordGateway.on_disconnect"
        await gateway.on_resumed()
        assert (
            next(item for item in store.runtime() if item.component == "discord").status
            == "success"
        )
        assert store.current(activity.id) == activity
        assert not store.pending_notices()
    finally:
        await gateway.close()


@pytest.mark.anyio
async def test_explicit_communication_keeps_every_field_and_internal_logs_private(
    store: LocalStore,
) -> None:
    """Only the selected message is delivered, including during expression failure."""
    activity = store.create("確認", ("条件",), "範囲", "noa", now=1)
    claimed = store.claim(1)
    assert claimed is not None
    silent = Outcome(
        action="continue",
        summary="内部の記録",
        rationale="内部の理由",
        next_step="続ける",
    )
    assert silent.communication is None
    store.finish(claimed, silent, 2)
    assert not store.pending_notices()
    claimed = store.claim(2)
    assert claimed is not None
    message = Communication(
        content="PUBLIC-RESULT",
        reason="PUBLIC-REASON",
        evidence=("PUBLIC-SOURCE",),
        uncertainty="PUBLIC-UNKNOWN",
        question="PUBLIC-QUESTION",
    )
    store.finish(
        claimed,
        Outcome(
            action="ask",
            summary="PRIVATE-LOG",
            rationale="PRIVATE-REASON",
            evidence=("PRIVATE-SOURCE",),
            next_step=message.question,
            communication=message,
        ),
        3,
    )

    class Speaker:
        async def render(self, notice: Notice, character: Character) -> str:
            assert notice.message == message
            assert "PRIVATE" not in notice.model_dump_json()
            raise ValueError("unavailable")

    output = store.root / "messages"
    assert await Communicator(store, FilePublisher(output), Speaker()).flush() == 1
    content = next(output.glob("*.md")).read_text()
    assert all(
        value in content
        for value in (
            message.content,
            message.reason,
            message.evidence[0],
            message.uncertainty,
            message.question,
        )
    )
    assert "PRIVATE" not in content
    facts = {fact.component: fact for fact in store.runtime()}
    assert facts["expression"].status == "failure"
    assert facts["delivery"].status == "success"
    assert store.current(activity.id).status == "waiting"


def test_question_must_match_the_actual_pending_question() -> None:
    """A question cannot be recorded with unrelated words sent to the master."""
    with pytest.raises(ValueError, match="question"):
        Outcome(
            action="ask",
            summary="確認",
            rationale="不明",
            next_step="Aですか？",
            communication=Communication(content="確認", question="Bですか？"),
        )
    with pytest.raises(ValueError, match="time"):
        RuntimeObservation(component="discord", status="success", source="test")
