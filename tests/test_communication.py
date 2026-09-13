"""Reporting failures never invalidate completed work or its evidence."""

from pathlib import Path
from typing import Any

import pytest

from app.contracts.messages.support import Character, Communication, Notice, Outcome
from app.infrastructure.communication import FilePublisher, GeminiSpeaker
from app.infrastructure.store import LocalStore
from app.usecases.support import Communicator


class RecordingPublisher:
    """Capture durable notice identities across retries."""

    def __init__(self) -> None:
        self.failed = True
        self.sent: list[Notice] = []

    async def send(self, notice: Notice, character: Character) -> None:
        """Record attempts, with a controllable delivery outage."""
        self.sent.append(notice)
        if self.failed:
            raise OSError("offline")


class FailingSpeaker:
    """Simulate an unavailable expression provider."""

    async def render(self, notice: Notice, character: Character) -> str:
        """Fail before a report is generated."""
        raise ValueError("unavailable")


def ready_notice(store: LocalStore) -> Notice:
    """Complete actual persisted work before exercising communication."""
    store.create("結果を調べる", ("根拠を残す",), "調査のみ", "noa", now=100)
    claimed = store.claim(100)
    assert claimed is not None
    store.finish(
        claimed,
        Outcome(
            action="complete",
            summary="根拠を確認しました。",
            communication=Communication(content="根拠を確認しました。"),
            rationale="条件を確認した",
            next_step="",
            achieved=(0,),
            evidence=("実行記録",),
        ),
        101,
    )
    return store.pending_notices()[0]


@pytest.mark.anyio
async def test_expression_outage_and_delivery_retry_do_not_rerun_work(
    store: LocalStore,
) -> None:
    """U7: unrendered and undelivered results survive a new process."""
    notice = ready_notice(store)
    publisher = RecordingPublisher()
    communicator = Communicator(store, publisher, FailingSpeaker())
    assert await communicator.flush() == 0
    assert store.current(notice.activity_id).status == "done"
    assert store.current(notice.activity_id).runs == 1
    stored = LocalStore(store.root).pending_notices()[0]
    assert stored.rendered == stored.content
    publisher.failed = False
    assert await Communicator(LocalStore(store.root), publisher).flush() == 1
    assert publisher.sent[0].id == publisher.sent[1].id
    assert publisher.sent[0].rendered == publisher.sent[1].rendered
    assert not store.pending_notices()


@pytest.mark.anyio
async def test_successful_expression_is_saved_but_never_becomes_memory(
    store: LocalStore,
) -> None:
    """U6/U7: human-facing wording is not fed back as a new fact."""
    notice = ready_notice(store)

    class Speaker:
        async def render(self, notice: Notice, character: Character) -> str:
            return "読みやすく整えた報告です。"

    output = store.root / "messages"
    communicator = Communicator(store, FilePublisher(output), Speaker())
    assert await communicator.flush() == 1
    assert "読みやすく" in (output / f"{notice.id}.md").read_text()
    assert all(
        "読みやすく" not in event.content
        for event in store.events(notice.activity_id)
        if event.kind != "delivered"
    )
    assert await communicator.flush() == 0


@pytest.mark.anyio
async def test_file_delivery_is_idempotent_even_before_marking_success(
    tmp_path: Path,
) -> None:
    """U7: retrying after a process crash replaces the same local notice file."""
    notice = Notice(
        id="abc",
        activity_id="activity",
        character_id="noa",
        message=Communication(content="内容"),
    )
    character = Character(id="noa", name="Noa", perspective="確認する", voice="短く")
    publisher = FilePublisher(tmp_path)
    await publisher.send(notice, character)
    await publisher.send(notice, character)
    assert len(list(tmp_path.iterdir())) == 1


@pytest.mark.anyio
async def test_gemini_is_given_expression_only_and_no_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The expression boundary receives neither work authority nor private history."""
    from app.infrastructure import communication as module

    requests: list[dict[str, Any]] = []
    closed: list[str] = []

    class FakeClient:
        def __init__(self, **kwargs: object) -> None:
            self.aio = self
            self.models = self

        async def generate_content(self, **kwargs: Any) -> Any:
            requests.append(kwargs)
            return type("Response", (), {"text": "報告です。"})()

        async def aclose(self) -> None:
            closed.append("async")

        def close(self) -> None:
            closed.append("sync")

    monkeypatch.setattr(module.genai, "Client", FakeClient)
    speaker = GeminiSpeaker("example", "configured-model")
    notice = Notice(
        id="a",
        activity_id="b",
        character_id="noa",
        message=Communication(
            content="確認した内容",
            reason="判断に必要",
            evidence=("確認した資料",),
            uncertainty="外部の状況は未確認",
            question="適用しますか？",
        ),
    )
    character = Character(
        id="noa", name="Noa", perspective="PRIVATE-PERSPECTIVE", voice="短く話す"
    )
    assert await speaker.render(notice, character) == "報告です。"
    assert requests[0]["config"].tools is None
    assert "PRIVATE-PERSPECTIVE" not in requests[0]["config"].system_instruction
    assert requests[0]["contents"] == notice.message.model_dump_json()
    await speaker.close()
    assert closed == ["async", "sync"]
