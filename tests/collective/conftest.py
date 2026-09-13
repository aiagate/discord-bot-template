"""Deterministic external abilities for acceptance scenarios."""

from pathlib import Path

import pytest

from app.contracts.messages.collective import (
    Character,
    CharacterContext,
    CollectiveSettings,
    Decision,
    ModelLimits,
    Speech,
    WorkContext,
    WorkResult,
)
from app.contracts.ports.collective import ExecutionRecorder
from app.infrastructure.collective.store import SQLiteCollectiveStore
from app.infrastructure.collective.workspace import CharacterWorkspaces
from app.usecases.collective.runtime import Collective


class ConversationDouble:
    """Replace the conversation provider without changing stored records."""

    def __init__(self) -> None:
        self.decisions: list[Decision | Exception] = []
        self.contexts: list[CharacterContext] = []
        self.rendered: list[Speech] = []
        self.render_error: Exception | None = None
        self.counts: list[int] = []
        self.model_limits = ModelLimits(
            model="test",
            input_tokens=1000,
            output_tokens=100,
            output_reserve=100,
            margin=0,
        )

    async def limits(self) -> ModelLimits:
        """Return configurable provider metadata."""
        return self.model_limits

    async def count(self, context: CharacterContext, speech: Speech | None) -> int:
        """Simulate provider counting independently of local estimates."""
        return self.counts.pop(0) if self.counts else 100

    async def converse(self, context: CharacterContext) -> Decision:
        """Return one queued decision and retain the exact admitted context."""
        self.contexts.append(context)
        decision = self.decisions.pop(0) if self.decisions else Decision()
        if isinstance(decision, Exception):
            raise decision
        return decision

    async def render(self, context: CharacterContext, speech: Speech) -> str:
        """Make the reporting boundary observable."""
        self.contexts.append(context)
        self.rendered.append(speech)
        if self.render_error is not None:
            raise self.render_error
        return (
            "比較ができました。費用はAが低く、保守性はBが優れます。実運用は未確認です。"
        )


class CodexDouble:
    """Capture actual work inputs without external side effects."""

    def __init__(self) -> None:
        self.results: list[WorkResult | Exception] = []
        self.contexts: list[WorkContext] = []
        self.interrupted: list[str] = []
        self.confirm_exit = True
        self.saved_output: str | None = None

    async def run_codex(
        self, context: WorkContext, record: ExecutionRecorder
    ) -> WorkResult:
        """Record an execution ID before yielding its observed result."""
        self.contexts.append(context)
        await record("thread_id", "test-thread")
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    async def interrupt(self, run_id: str) -> bool:
        """Allow tests to simulate unconfirmed child termination."""
        self.interrupted.append(run_id)
        return self.confirm_exit

    async def recover(self, execution: dict[str, str]) -> bool:
        """Simulate confirmation of previous process exit."""
        return self.confirm_exit

    def saved_result(self, execution: dict[str, str]) -> str | None:
        """Simulate an output file saved immediately before a crash."""
        return self.saved_output


@pytest.fixture
def collective(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Collective:
    """Create real SQLite and projections with test-only external abilities."""
    monkeypatch.setenv("CODEX_HOME", str(tmp_path / "codex"))
    skill = tmp_path / "agy" / "SKILL.md"
    skill.parent.mkdir()
    skill.write_text("# AGY test skill\n")
    characters = {
        name: Character(
            id=name,
            name=name.title(),
            persona=f"{name} personality",
            public_profile=f"{name} role",
        )
        for name in ("alice", "bob")
    }
    root = tmp_path / "data"
    return Collective(
        SQLiteCollectiveStore(root),
        characters,
        "Prepare useful comparisons; keep work local.",
        ConversationDouble(),
        CodexDouble(),
        CharacterWorkspaces(root, skill),
        root,
        CollectiveSettings(reflection_seconds=100, retry_seconds=1, max_round=3),
    )
