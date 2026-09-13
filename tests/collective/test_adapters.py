"""Validate exact provider requests and classify external failure boundaries."""

import json
from typing import Any, cast
from unittest.mock import MagicMock

import aiohttp
import pytest

from app.contracts.messages.collective import (
    CharacterContext,
    Decision,
    Speech,
    SpeechPart,
)
from app.contracts.ports.collective import InputTooLarge
from app.infrastructure.collective.gemini import GeminiConversation
from app.infrastructure.collective.webhook import WebhookPublisher
from app.usecases.collective.runtime import Collective


class Response:
    """Small context-managed HTTP response double."""

    def __init__(self, status: int, body: dict[str, Any]) -> None:
        self.status = status
        self.body = body

    async def __aenter__(self) -> "Response":
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        """Return the decoded service response."""
        return self.body


def context_for(collective: Collective) -> CharacterContext:
    """Build a real queued input snapshot."""
    collective.receive("1", "Compare options", "master", 1, "alice")
    turn = collective._claim("conversation", 1)
    assert turn is not None and turn.context is not None
    return turn.context


@pytest.mark.anyio
@pytest.mark.parametrize("times", [False, True])
async def test_gemini_counts_actual_generation_request_and_refreshes_model(
    collective: Collective,
    times: bool,
) -> None:
    context = context_for(collective)
    if times:
        context = context.model_copy(update={"scope": "times", "purpose": "reflection"})
    session = MagicMock(spec=aiohttp.ClientSession)
    session.request.side_effect = [
        Response(200, {"inputTokenLimit": 1000, "outputTokenLimit": 200}),
        Response(200, {"totalTokens": 300}),
        Response(
            200,
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {
                            "parts": [
                                {
                                    "text": Decision(
                                        speech="はい。", inspect=False
                                    ).model_dump_json()
                                }
                            ]
                        },
                    }
                ]
            },
        ),
        Response(200, {"inputTokenLimit": 2000, "outputTokenLimit": 300}),
    ]
    adapter = GeminiConversation(
        cast(aiohttp.ClientSession, session), "secret", max_output_tokens=100, margin=10
    )
    assert (await adapter.limits()).budget == 890
    assert await adapter.count(context, None) == 300
    assert (await adapter.converse(context)).speech == "はい。"
    counting = session.request.call_args_list[1].kwargs["json"][
        "generateContentRequest"
    ]
    generated = session.request.call_args_list[2].kwargs["json"]
    assert counting == {"model": f"models/{adapter.model}", **generated}
    assert counting["systemInstruction"]
    assert counting["generationConfig"]["responseJsonSchema"]
    parts = counting["contents"][0]["parts"]
    assert len(parts) == (2 if times else 1)
    assert json.loads(parts[0]["text"])["context"] == context.model_dump(mode="json")
    assert "secret" not in json.dumps(counting)
    adapter.model = "replacement"
    assert (await adapter.limits()).input_tokens == 2000


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,message,error",
    [
        (400, "input token count exceeds maximum", InputTooLarge),
        (429, "rate limit", RuntimeError),
        (500, "server failure", RuntimeError),
    ],
)
async def test_gemini_overflow_is_distinct_from_transient_failure(
    collective: Collective, status: int, message: str, error: type[Exception]
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.request.return_value = Response(status, {"error": {"message": message}})
    adapter = GeminiConversation(cast(aiohttp.ClientSession, session), "secret")
    with pytest.raises(error):
        await adapter.converse(context_for(collective))


@pytest.mark.anyio
async def test_gemini_render_uses_saved_facts_and_rejects_truncation(
    collective: Collective,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.request.side_effect = [
        Response(
            200,
            {
                "candidates": [
                    {
                        "finishReason": "STOP",
                        "content": {"parts": [{"text": '{"body":"できました。"}'}]},
                    }
                ]
            },
        ),
        Response(200, {"candidates": [{"finishReason": "MAX_TOKENS"}]}),
    ]
    adapter = GeminiConversation(cast(aiohttp.ClientSession, session), "secret")
    context = context_for(collective)
    speech = Speech(id="s", character_id="alice", scope="master", origin="s")
    assert await adapter.render(context, speech) == "できました。"
    assert (
        '"speech"'
        in session.request.call_args.kwargs["json"]["contents"][0]["parts"][0]["text"]
    )
    with pytest.raises(ValueError, match="finish"):
        await adapter.converse(context)


@pytest.mark.anyio
@pytest.mark.parametrize(
    "status,body,expected",
    [
        (200, {"id": "123"}, "sent"),
        (200, {}, "unknown"),
        (204, {}, "unknown"),
        (429, {"retry_after": 5}, "rejected"),
        (403, {}, "rejected"),
        (500, {}, "unknown"),
    ],
)
async def test_webhook_posts_once_with_character_identity(
    collective: Collective, status: int, body: dict[str, Any], expected: str
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.return_value = Response(status, body)
    publisher = WebhookPublisher(
        cast(aiohttp.ClientSession, session),
        {"master": "https://discord.com/api/webhooks/1/token"},
    )
    character = collective.characters["alice"].model_copy(
        update={"avatar_url": "https://example.com/alice.png"}
    )
    part = SpeechPart(
        id="s/0", speech_id="s", index=0, destination="master:1", body="結果です。"
    )
    assert (await publisher.send(part, character)).status == expected
    session.post.assert_called_once()
    call = session.post.call_args.kwargs
    assert call["params"] == {"wait": "true"}
    assert call["json"]["username"] == "Alice"
    assert call["json"]["avatar_url"].endswith("alice.png")
    assert call["json"]["allowed_mentions"] == {"parse": []}
    assert call["allow_redirects"] is False


@pytest.mark.anyio
async def test_webhook_reconciliation_never_reposts_missing_message(
    collective: Collective,
) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.get.side_effect = [
        Response(404, {}),
        Response(200, {"id": "123", "content": "body"}),
    ]
    publisher = WebhookPublisher(
        cast(aiohttp.ClientSession, session),
        {"master": "https://discord.com/api/webhooks/1/token"},
    )
    part = SpeechPart(
        id="s/0",
        speech_id="s",
        index=0,
        destination="master:1",
        body="body",
        message_id="123",
    )
    assert (await publisher.reconcile(part)).status == "unknown"
    assert (await publisher.reconcile(part)).status == "sent"
    session.post.assert_not_called()
    part.message_id = None
    assert (await publisher.reconcile(part)).status == "unknown"


@pytest.mark.anyio
async def test_webhook_network_failure_is_ambiguous(collective: Collective) -> None:
    session = MagicMock(spec=aiohttp.ClientSession)
    session.post.side_effect = aiohttp.ClientConnectionError()
    session.get.side_effect = aiohttp.ClientConnectionError()
    publisher = WebhookPublisher(
        cast(aiohttp.ClientSession, session),
        {"master": "https://discord.com/api/webhooks/1/token"},
    )
    part = SpeechPart(
        id="s/0",
        speech_id="s",
        index=0,
        destination="master:1",
        body="body",
        message_id="123",
    )
    assert (
        await publisher.send(part, collective.characters["alice"])
    ).status == "unknown"
    assert (await publisher.reconcile(part)).status == "unknown"


def test_webhook_rejects_arbitrary_destination() -> None:
    with pytest.raises(ValueError):
        WebhookPublisher(
            cast(aiohttp.ClientSession, MagicMock()), {"master": "https://example.com"}
        )
