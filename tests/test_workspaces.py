"""Character ownership, independent checkouts, and continuity across restarts."""

import os
import subprocess
from pathlib import Path

import pytest

from app.contracts.messages.support import Communication, Memory, Outcome
from app.infrastructure.store import LocalStore
from app.infrastructure.workspace import prepare_repositories


def test_handoff_preserves_personal_memory_and_editable_guidance(
    store: LocalStore,
) -> None:
    """A handoff moves the activity, while each participant keeps their own work."""
    first = store.workspace("dorothy")
    second = store.workspace("astra")
    guide = first / "AGENTS.md"
    guide.write_text(guide.read_text() + "\n利用者が追加した案内\n")
    store.initialize()
    assert "利用者が追加した案内" in guide.read_text()
    assert "利用者が追加した案内" not in (second / "AGENTS.md").read_text()
    activity = store.create("支援", ("確認",), "資料", "dorothy", now=1)
    claimed = store.claim(1)
    assert claimed is not None
    source_context = store.context(claimed, 1)
    artifact = source_context.task_root / "finding.md"
    artifact.write_text("調査結果")
    store.finish(
        claimed,
        Outcome(
            action="handoff",
            summary="観点の引継ぎ",
            rationale="別の確認が必要",
            next_step="調査結果を確認する",
            recipient="astra",
            evidence=(str(artifact),),
            memories=(Memory(key="lesson", content="Dorothyの理解"),),
        ),
        2,
    )
    next_claim = store.claim(2)
    assert next_claim is not None
    target_context = store.context(next_claim, 2)
    assert target_context.workspace == second
    assert target_context.activity.id == activity.id
    assert target_context.continuity.last_decision is not None
    assert str(artifact) in target_context.continuity.last_decision.content
    assert artifact.read_text() == "調査結果"
    store.finish(
        next_claim,
        Outcome(
            action="sleep",
            delay_seconds=60,
            summary="確認",
            rationale="次回待機",
            next_step="変化を確認",
            memories=(Memory(key="lesson", content="Astraの理解"),),
        ),
        3,
    )
    store.receive(activity.id, "今回どう思った？")
    message = store.pending_conversation()
    assert message is not None
    conversation = LocalStore(store.root).conversation_context(message)
    assert "Dorothyの理解" in (first / "memory/lesson.md").read_text()
    assert "Astraの理解" in (second / "memory/lesson.md").read_text()
    assert (
        conversation.memories["lesson"]
        == (target_context.memory_root / "lesson.md").read_text().strip()
    )
    assert "Dorothyの理解" not in conversation.memories["lesson"]
    assert not store.pending_notices()


def test_continuity_survives_a_full_tool_window_and_process_restart(
    store: LocalStore,
) -> None:
    """Unanswered questions and delivered words survive unrelated tool records."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    claimed = store.claim(1)
    assert claimed is not None
    store.finish(
        claimed,
        Outcome(
            action="ask",
            summary="確認待ち",
            rationale="本人の意向が必要",
            next_step="AとBのどちらですか？",
            communication=Communication(
                content="選択を確認します。", question="AとBのどちらですか？"
            ),
        ),
        2,
    )
    notice = store.pending_notices()[0]
    before_delivery = store.context(store.current(activity.id), 2)
    assert before_delivery.continuity.last_delivery is None
    store.save_rendered(notice.id, "AとBのどちらですか？")
    store.delivered(notice.id)
    for index in range(40):
        store.record(claimed, "commandExecution", f"操作{index}", 3 + index)
    reopened = LocalStore(store.root)
    context = reopened.context(reopened.current(activity.id), 50)
    assert all(event.kind == "commandExecution" for event in context.events)
    assert context.continuity.last_decision is not None
    assert context.continuity.last_delivery is not None
    assert context.continuity.last_delivery.content == "AとBのどちらですか？"
    assert context.continuity.pending_question == "AとBのどちらですか？"
    reopened.receive(activity.id, "こんにちは")
    assert reopened.continuity(activity.id).pending_question is not None
    reopened.inform(activity.id, "Aにします", now=51)
    assert reopened.continuity(activity.id).pending_question is None


def test_workspace_refuses_a_link_into_another_characters_memory(
    store: LocalStore,
) -> None:
    """A directory alias cannot silently change the owner of persisted memory."""
    memory = store.workspace("noa") / "memory"
    memory.rmdir()
    memory.symlink_to(store.workspace("astra") / "memory", target_is_directory=True)
    with pytest.raises(ValueError, match="リンク"):
        store.workspace("noa")


def test_context_does_not_write_through_a_redirected_task_directory(
    store: LocalStore,
) -> None:
    """A redirected task path cannot make the host overwrite another owner."""
    workspace = store.workspace("noa")
    target = store.workspace("astra")
    (workspace / "tasks").symlink_to(target, target_is_directory=True)
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    with pytest.raises(ValueError, match="リンク"):
        store.context(activity, 1)
    assert not (target / activity.id).exists()


@pytest.mark.anyio
async def test_ghq_prepares_independent_repos_without_resetting_local_changes(
    store: LocalStore,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Real ghq and Git preserve separate checkouts, including after a repeat run."""
    source = tmp_path / "source.git"
    subprocess.run(
        ["git", "init", "-q", "--initial-branch=main", str(source)], check=True
    )
    (source / "subject.txt").write_text("original")
    subprocess.run(["git", "-C", str(source), "add", "subject.txt"], check=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
        check=True,
    )
    url = "https://example.invalid/team/subject.git"
    monkeypatch.setenv("GIT_CONFIG_COUNT", "1")
    monkeypatch.setenv("GIT_CONFIG_KEY_0", f"url.{source.as_uri()}.insteadOf")
    monkeypatch.setenv("GIT_CONFIG_VALUE_0", url)
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    (first,) = await prepare_repositories(store.workspace("noa"), (url,))
    (second,) = await prepare_repositories(store.workspace("astra"), (url,))
    assert first != second
    assert first.is_relative_to(store.workspace("noa") / "repos")
    assert second.is_relative_to(store.workspace("astra") / "repos")
    (first / "subject.txt").write_text("Noa's uncommitted work")
    assert (second / "subject.txt").read_text() == "original"
    (again,) = await prepare_repositories(store.workspace("noa"), (url,))
    assert again == first
    assert (first / "subject.txt").read_text() == "Noa's uncommitted work"
    assert os.environ.get("GHQ_ROOT") != str(first)


@pytest.mark.anyio
async def test_repository_preparation_reports_failure_without_guessing_a_path(
    store: LocalStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed clone is not reported as a ready repository."""
    monkeypatch.setenv("GIT_ALLOW_PROTOCOL", "file")
    with pytest.raises(RuntimeError, match="ghq"):
        await prepare_repositories(
            store.workspace("noa"), ("https://example.invalid/missing.git",)
        )
