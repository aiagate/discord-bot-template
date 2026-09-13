"""SDK events remain evidence even if final output is invalid or interrupted."""

import os
import tomllib
from collections.abc import AsyncIterator
from typing import Any

import pytest
from openai_codex import ApprovalMode, Sandbox
from openai_codex.generated.v2_all import (
    AgentMessageThreadItem,
    ItemCompletedNotification,
    ItemStartedNotification,
    MessagePhase,
    ThreadItem,
    Turn,
    TurnCompletedNotification,
    TurnStatus,
)
from openai_codex.models import Notification

from app.contracts.messages.support import Communication, Outcome
from app.infrastructure.codex import CodexThinker
from app.infrastructure.store import LocalStore


def item(text: str) -> ItemCompletedNotification:
    """Use real SDK types so event-field changes fail this adapter test."""
    return ItemCompletedNotification(
        thread_id="thread",
        turn_id="turn",
        completed_at_ms=1,
        item=ThreadItem(
            root=AgentMessageThreadItem(
                id="message",
                text=text,
                type="agentMessage",
                phase=MessagePhase.final_answer,
            )
        ),
    )


@pytest.mark.anyio
@pytest.mark.parametrize(
    "case", ["complete", "invalid", "missing_end", "failed", "tool_limit"]
)
async def test_codex_stream_validation_and_runtime_cleanup(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch, case: str
) -> None:
    """Explicit decisions, not transport completion, govern work state."""
    from app.infrastructure import codex as module

    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)
    context = store.context(activity, 1)
    events: list[Notification] = []
    if case == "tool_limit":
        event = ItemStartedNotification.model_validate(
            {
                "threadId": "thread",
                "turnId": "turn",
                "startedAtMs": 1,
                "item": {"type": "webSearch", "id": "search", "query": "docs"},
            }
        )
        events.append(Notification(method="item/started", payload=event))
    else:
        text = (
            "invalid"
            if case == "invalid"
            else Outcome(
                action="complete",
                summary="確認済み",
                communication=Communication(content="確認済み"),
                rationale="条件を満たした",
                next_step="",
                achieved=(0,),
                evidence=("実行記録",),
            ).model_dump_json()
        )
        events.append(Notification(method="item/completed", payload=item(text)))
    if case != "missing_end":
        events.append(
            Notification(
                method="turn/completed",
                payload=TurnCompletedNotification(
                    thread_id="thread",
                    turn=Turn(
                        id="turn",
                        items=[],
                        status=TurnStatus.failed
                        if case == "failed"
                        else TurnStatus.completed,
                    ),
                ),
            )
        )
    started: list[dict[str, Any]] = []
    turned: list[dict[str, Any]] = []
    interrupted: list[bool] = []
    closed: list[bool] = []
    recorded: list[tuple[str, str]] = []

    class Handle:
        async def stream(self) -> AsyncIterator[Notification]:
            for event in events:
                yield event

        async def interrupt(self) -> None:
            interrupted.append(True)

    class Thread:
        id = "thread"

        async def turn(self, prompt: str, **kwargs: Any) -> Handle:
            turned.append(kwargs)
            assert "memory_root" in prompt
            return Handle()

    class Client:
        def __init__(self, config: object) -> None:
            pass

        async def thread_start(self, **kwargs: Any) -> Thread:
            started.append(kwargs)
            return Thread()

        async def close(self) -> None:
            closed.append(True)

    async def record(kind: str, content: str) -> None:
        recorded.append((kind, content))

    monkeypatch.setattr(module, "AsyncCodex", Client)
    thinker = CodexThinker(max_tools=0 if case == "tool_limit" else 80)
    if case == "complete":
        outcome = await thinker.run(context, record)
        assert outcome.action == "complete"
    else:
        with pytest.raises((ValueError, RuntimeError)):
            await thinker.run(context, record)
    assert closed == [True]
    assert bool(interrupted) == (case in {"missing_end", "tool_limit"})
    assert started[0]["sandbox"] == Sandbox.workspace_write
    assert started[0]["approval_mode"] == ApprovalMode.deny_all
    assert "next_step" in turned[0]["output_schema"]["required"]
    assert (
        "question" in turned[0]["output_schema"]["$defs"]["Communication"]["required"]
    )
    if case == "invalid":
        assert ("response", "invalid") in recorded


def test_codex_environment_excludes_channel_and_expression_credentials(
    store: LocalStore, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Only the worker's own authentication context reaches its process."""
    activity = store.create("目的", ("条件",), "範囲", "noa", now=1)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "discord-secret")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setenv("DISCORD_WEBHOOK_URL", "webhook-secret")
    config = CodexThinker().config(store.context(activity, 1))
    arguments = config.launch_args_override
    assert arguments is not None
    assert "-i" in arguments
    assert not any(
        any(
            secret in value
            for secret in ("discord-secret", "gemini-secret", "webhook-secret")
        )
        for value in arguments
    )
    assert f"PATH={os.environ['PATH']}" in arguments
    overrides = {
        key: value
        for index, argument in enumerate(arguments)
        if argument == "--config"
        for key, value in tomllib.loads(arguments[index + 1]).items()
    }
    shell = overrides["shell_environment_policy"]
    assert shell["set"]["GHQ_ROOT"] == str(store.workspace("noa") / "repos")
    assert shell["set"]["TMPDIR"] == str(store.workspace("noa") / ".tmp")
    assert "sandbox_workspace_write.exclude_slash_tmp=true" in arguments
    assert "sandbox_workspace_write.exclude_tmpdir_env_var=true" in arguments
    assert "sandbox_workspace_write.writable_roots=[]" in arguments
