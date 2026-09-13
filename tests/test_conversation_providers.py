"""Different providers obey the same conversation contract and have no work tools."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import cli
from app.contracts.messages.conversation import ConversationDecision
from app.infrastructure import conversation as module
from app.infrastructure.store import LocalStore


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["gemini", "openai"])
@pytest.mark.parametrize("valid", [True, False])
async def test_providers_return_the_same_decision_without_executing_tools(
    store: LocalStore,
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
    valid: bool,
) -> None:
    """Provider conversion does not own state, identity, or expression."""
    activity = store.create("支援", ("確認",), "資料", "noa", now=1)
    store.receive(activity.id, "こんにちは")
    message = store.pending_conversation()
    assert message is not None
    context = store.conversation_context(message)
    expected = ConversationDecision(
        action="reply", content="こんにちは。", rationale="挨拶に応える"
    )
    if provider == "gemini":
        call = AsyncMock(
            return_value=SimpleNamespace(
                text=expected.model_dump_json() if valid else None
            )
        )
        close = AsyncMock()
        client = SimpleNamespace(
            aio=SimpleNamespace(
                models=SimpleNamespace(generate_content=call), aclose=close
            ),
            close=Mock(),
        )
        monkeypatch.setattr(module.genai, "Client", Mock(return_value=client))
        thinker = module.GeminiConversationThinker("key", "chosen-model")
    else:
        call = AsyncMock(
            return_value=SimpleNamespace(output_parsed=expected if valid else None)
        )
        close = AsyncMock()
        client = SimpleNamespace(responses=SimpleNamespace(parse=call), close=close)
        monkeypatch.setattr(module, "AsyncOpenAI", Mock(return_value=client))
        thinker = module.OpenAIConversationThinker("key", "chosen-model")
    try:
        if valid:
            assert await thinker.think(context) == expected
        else:
            with pytest.raises(ValueError):
                await thinker.think(context)
    finally:
        await thinker.close()
    close.assert_awaited_once()
    kwargs = call.call_args.kwargs
    assert kwargs["model"] == "chosen-model"
    assert "tools" not in kwargs
    if provider == "gemini":
        assert kwargs["contents"] == context.model_dump_json()
        assert not kwargs["config"].tools
        assert kwargs["config"].response_json_schema == expected.model_json_schema()
    else:
        assert kwargs["input"] == context.model_dump_json()
        assert kwargs["text_format"] is ConversationDecision
        assert kwargs["store"] is False
    assert store.current(activity.id) == activity
    assert not store.pending_notices()


@pytest.mark.anyio
@pytest.mark.parametrize("provider", ["gemini", "openai"])
async def test_configuration_can_replace_provider_and_model(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    """Model choice is made at composition and does not select the expression model."""
    monkeypatch.setenv("COLLECTIVE_CONVERSATION_PROVIDER", provider)
    monkeypatch.setenv("COLLECTIVE_CONVERSATION_MODEL", "conversation-model")
    monkeypatch.setenv("COLLECTIVE_GEMINI_MODEL", "expression-model")
    monkeypatch.setenv("GEMINI_API_KEY", "test-key")
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    thinker = cli.make_conversation_thinker()
    speaker = cli.make_speaker()
    assert speaker is not None
    try:
        if provider == "gemini":
            assert isinstance(thinker, module.GeminiConversationThinker)
        else:
            assert isinstance(thinker, module.OpenAIConversationThinker)
        assert thinker.model == "conversation-model"
        assert speaker.model == "expression-model"
    finally:
        await thinker.close()
        await speaker.close()


@pytest.mark.parametrize("provider", ["gemini", "openai", "unsupported"])
def test_bad_provider_settings_fail_before_starting_work(
    monkeypatch: pytest.MonkeyPatch,
    provider: str,
) -> None:
    """A missing configuration cannot silently route conversation back to Codex."""
    for name in (
        "GEMINI_API_KEY",
        "OPENAI_API_KEY",
        "COLLECTIVE_CONVERSATION_MODEL",
        "COLLECTIVE_GEMINI_MODEL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("COLLECTIVE_CONVERSATION_PROVIDER", provider)
    with pytest.raises(ValueError):
        cli.make_conversation_thinker()
