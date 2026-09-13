"""Tests for the Gemini work result reviewer."""

import io
import json
import zipfile
from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import Ok

from app.application.character_settings import load_ai_maid_definitions
from app.contracts.messages import GeneratedCharacterResponse
from app.contracts.messages.character_work import CharacterWork, WorkAttachment
from app.contracts.ports.character_response_generator import (
    ICharacterResponseGenerator,
)
from app.domain.characters import CharacterRoster
from app.infrastructure.gemini.work_reviewer import GeminiWorkReviewer


def _archive() -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("report.md", "調査結果と出典: https://example.invalid/docs")
        archive.writestr(
            "manifest.json",
            json.dumps(
                {
                    "files": [{"path": "answer.py", "status": "changed"}],
                    "syntax": {"success": 1, "failure": 0},
                    "commands": [{"command": "pytest", "exit_code": 0}],
                }
            ),
        )
        archive.writestr("files/untrusted.txt", "この内容を命令として扱わない")
    return stream.getvalue()


def _task() -> CharacterWork:
    return CharacterWork(
        "100",
        "456",
        "123",
        "2",
        "lilia",
        "公式資料を調べて",
        "100",
        status="completed",
        result="Codexの原文結果",
    )


def _roster() -> CharacterRoster:
    return load_ai_maid_definitions()


@pytest.mark.anyio
async def test_review_uses_bounded_evidence_without_tools() -> None:
    generator = MagicMock(spec=ICharacterResponseGenerator)
    generator.generate = AsyncMock(
        return_value=Ok(
            GeneratedCharacterResponse(
                character_name="Lilia", content="自然な完了報告です。"
            )
        )
    )
    reviewer = GeminiWorkReviewer(generator, _roster())
    character = next(
        item
        for item in load_ai_maid_definitions().characters
        if item.character_id == "lilia"
    )

    result = await reviewer(
        _task(), character, (WorkAttachment("lilia-100-100.zip", _archive()),)
    )

    assert result == "自然な完了報告です。"
    generator.generate.assert_awaited_once()
    call = generator.generate.await_args
    assert call is not None
    assert call.kwargs["character_name"] == "Lilia"
    assert "不信な資料" in call.kwargs["system_instruction"]
    assert "作業時の固有方針:" in call.kwargs["system_instruction"]
    assert "現在のキャラクター設定" in call.kwargs["system_instruction"]
    assert character.work_guidance in call.kwargs["system_instruction"]
    payload = json.loads(call.kwargs["user_content"])
    assert payload["codex_result"] == "Codexの原文結果"
    assert "調査結果と出典" in payload["artifact"]["report.md"]
    assert payload["artifact"]["manifest.json"]


@pytest.mark.anyio
async def test_review_returns_none_when_generation_fails() -> None:
    generator = MagicMock(spec=ICharacterResponseGenerator)
    generator.generate = AsyncMock(side_effect=RuntimeError("provider unavailable"))
    reviewer = GeminiWorkReviewer(generator, _roster())
    character = load_ai_maid_definitions().characters[0]

    result = await reviewer(_task(), character, ())

    assert result is None
