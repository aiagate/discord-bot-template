"""Tests for the structured Gemini user-memory adapter."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from flow_res import is_err, is_ok

from app.contracts.messages.user_memory import (
    UserMemoryExtractionRequest,
    UserMemorySource,
)
from app.infrastructure.gemini.user_memory_extractor import (
    GeminiUserMemoryExtractor,
)


def _request() -> UserMemoryExtractionRequest:
    """Create one extraction request without exposing canonical IDs to Gemini."""
    return UserMemoryExtractionRequest(
        user_id="01USER",
        day="2026-09-11",
        raw_logs=[
            UserMemorySource(
                message_id="message-1",
                user_id="01USER",
                platform="DISCORD",
                author_kind="user",
                external_sender_id="discord-alice",
                content="朝に作業する",
                occurred_at=datetime(2026, 9, 11, 1, tzinfo=UTC),
            )
        ],
    )


def _client(response_text: str) -> MagicMock:
    """Build a minimal async Gemini client double."""
    client = MagicMock()
    client.aio.models.generate_content = AsyncMock(
        return_value=MagicMock(text=response_text)
    )
    client.aio.aclose = AsyncMock()
    return client


@pytest.mark.anyio
async def test_extractor_validates_structured_result_and_minimizes_identity_payload() -> (
    None
):
    """Parse the strict response schema and omit owner/provider identifiers."""
    client = _client(
        json.dumps(
            {
                "profile_patch": None,
                "timeline_patches": [],
                "source_evaluations": [
                    {"message_id": "message-1", "disposition": "not_memorable"}
                ],
            }
        )
    )
    extractor = GeminiUserMemoryExtractor(client, "test-model")

    result = await extractor.extract(_request())

    assert is_ok(result)
    contents = client.aio.models.generate_content.await_args.kwargs["contents"]
    payload = json.loads(contents)
    assert payload["raw_logs"][0] == {
        "message_id": "message-1",
        "platform": "DISCORD",
        "author_kind": "user",
        "content": "朝に作業する",
        "occurred_at": "2026-09-11T01:00:00+00:00",
    }
    assert "user_id" not in payload
    await extractor.aclose()
    client.aio.aclose.assert_awaited_once()
    client.close.assert_called_once()


@pytest.mark.anyio
async def test_extractor_rejects_invalid_structured_result() -> None:
    """Return an extraction error instead of accepting malformed model output."""
    extractor = GeminiUserMemoryExtractor(_client("{}"), "test-model")

    result = await extractor.extract(_request())

    assert is_err(result)
