"""Tests for LINE entrypoint helpers."""

from datetime import UTC, datetime
from importlib import import_module
from types import ModuleType, SimpleNamespace
from typing import cast
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import Request
from flow_res import Err, Ok
from linebot.v3.webhooks import Event, FollowEvent, MessageEvent, TextMessageContent
from starlette.types import Message

from app.application.mediator import ApplicationMediator
from app.usecases.chat.save_line_chat import SaveLineChatCommand
from app.usecases.result import ErrorType, UseCaseError


def _load_line_main(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("LINE_CHANNEL_SECRET", "secret")
    monkeypatch.setenv("LINE_CHANNEL_ACCESS_TOKEN", "token")
    monkeypatch.setenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
    module_name = "app.presentation.line.__main__"
    import sys

    sys.modules.pop(module_name, None)
    return import_module(module_name)


def test_line_timestamp_conversion_rejects_invalid_value(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Malformed LINE timestamps are rejected instead of being replaced."""
    line_main = _load_line_main(monkeypatch)

    with pytest.raises(ValueError, match="integer"):
        line_main._occurred_at_from_line_timestamp("invalid")


@pytest.mark.anyio
async def test_handle_callback_saves_message(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test LINE webhook handling on a successful save."""
    line_main = _load_line_main(monkeypatch)

    class FakeUserSource:
        def __init__(self, user_id: str) -> None:
            self.user_id = user_id

    class FakeTextMessageContent:
        def __init__(self, text: str) -> None:
            self.id = "msg-1"
            self.text = text
            self.emojis = None
            self.quoted_message_id = None
            self.mark_as_read_token = None

    class FakeMessageEvent:
        def __init__(
            self,
            message: FakeTextMessageContent,
            source: FakeUserSource,
            reply_token: str,
            timestamp: int,
        ) -> None:
            self.message = message
            self.source = source
            self.reply_token = reply_token
            self.timestamp = timestamp

    fake_event = FakeMessageEvent(
        message=FakeTextMessageContent("hello"),
        source=FakeUserSource("u1"),
        reply_token="reply-token",
        timestamp=1_700_000_123_456,
    )

    monkeypatch.setattr(line_main, "MessageEvent", FakeMessageEvent)
    monkeypatch.setattr(line_main, "TextMessageContent", FakeTextMessageContent)
    monkeypatch.setattr(line_main, "UserSource", FakeUserSource)
    monkeypatch.setattr(line_main.parser, "parse", Mock(return_value=[fake_event]))
    send_async = AsyncMock(return_value=Ok(None))
    mediator = cast(
        ApplicationMediator,
        SimpleNamespace(send_async=send_async),
    )

    line_bot_api = AsyncMock()
    request = SimpleNamespace(
        headers={"X-Line-Signature": "signature"},
        body=AsyncMock(return_value=b"body"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                line_bot_api=line_bot_api,
                mediator=mediator,
            )
        ),
    )

    result = await line_main.handle_callback(request)

    assert result == "OK"
    line_bot_api.reply_message.assert_not_awaited()
    send_async.assert_awaited_once()
    await_args = send_async.await_args
    assert await_args is not None
    command = await_args.args[0]
    assert command.occurred_at == datetime(
        2023,
        11,
        14,
        22,
        15,
        23,
        456000,
        tzinfo=UTC,
    )


@pytest.mark.anyio
async def test_handle_callback_replies_on_save_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test LINE webhook error handling when save fails."""
    line_main = _load_line_main(monkeypatch)

    class FakeUserSource:
        def __init__(self, user_id: str) -> None:
            self.user_id = user_id

    class FakeTextMessageContent:
        def __init__(self, text: str) -> None:
            self.id = "msg-1"
            self.text = text
            self.emojis = None
            self.quoted_message_id = None
            self.mark_as_read_token = None

    class FakeMessageEvent:
        def __init__(
            self,
            message: FakeTextMessageContent,
            source: FakeUserSource,
            reply_token: str,
            timestamp: int,
        ) -> None:
            self.message = message
            self.source = source
            self.reply_token = reply_token
            self.timestamp = timestamp

    fake_event = FakeMessageEvent(
        message=FakeTextMessageContent("hello"),
        source=FakeUserSource("u1"),
        reply_token="reply-token",
        timestamp=1_700_000_123_456,
    )

    monkeypatch.setattr(line_main, "MessageEvent", FakeMessageEvent)
    monkeypatch.setattr(line_main, "TextMessageContent", FakeTextMessageContent)
    monkeypatch.setattr(line_main, "UserSource", FakeUserSource)
    monkeypatch.setattr(line_main.parser, "parse", Mock(return_value=[fake_event]))
    send_async = AsyncMock(
        return_value=Err(
            UseCaseError(
                type=ErrorType.UNEXPECTED,
                message="save failed",
            )
        ),
    )
    mediator = cast(
        ApplicationMediator,
        SimpleNamespace(send_async=send_async),
    )

    line_bot_api = AsyncMock()
    request = SimpleNamespace(
        headers={"X-Line-Signature": "signature"},
        body=AsyncMock(return_value=b"body"),
        app=SimpleNamespace(
            state=SimpleNamespace(
                line_bot_api=line_bot_api,
                mediator=mediator,
            )
        ),
    )

    result = await line_main.handle_callback(request)

    assert result is None
    line_bot_api.reply_message.assert_awaited_once()


def _text_event(text: str, sender: str, timestamp: int) -> MessageEvent:
    event = MessageEvent.from_dict(
        {
            "type": "message",
            "message": {
                "type": "text",
                "id": f"msg-{sender}",
                "text": text,
                "quoteToken": f"quote-{sender}",
            },
            "source": {"type": "user", "userId": sender},
            "replyToken": f"reply-{sender}",
            "timestamp": timestamp,
            "mode": "active",
            "webhookEventId": f"event-{sender}",
            "deliveryContext": {"isRedelivery": False},
        }
    )
    assert isinstance(event, MessageEvent)
    assert isinstance(event.message, TextMessageContent)
    return event


def _batch_request(
    monkeypatch: pytest.MonkeyPatch,
    line_main: ModuleType,
    events: list[Event],
    send_async: AsyncMock,
    *,
    wrapped: bool = False,
) -> tuple[Request, AsyncMock]:
    parsed = SimpleNamespace(events=events) if wrapped else events
    monkeypatch.setattr(line_main.parser, "parse", Mock(return_value=parsed))
    line_bot_api = AsyncMock()

    async def receive() -> Message:
        return {"type": "http.request", "body": b"body", "more_body": False}

    request = Request(
        {
            "type": "http",
            "headers": [(b"x-line-signature", b"signature")],
            "app": SimpleNamespace(
                state=SimpleNamespace(
                    mediator=SimpleNamespace(send_async=send_async),
                    line_bot_api=line_bot_api,
                )
            ),
        },
        receive=receive,
    )
    return request, line_bot_api


@pytest.mark.anyio
@pytest.mark.parametrize("wrapped", [False, True], ids=["list", "object.events"])
async def test_handle_callback_saves_all_messages_in_order(
    monkeypatch: pytest.MonkeyPatch, wrapped: bool
) -> None:
    """Both parser representations preserve every message and its event data."""
    line_main = _load_line_main(monkeypatch)
    send_async = AsyncMock(return_value=Ok(None))
    request, api = _batch_request(
        monkeypatch,
        line_main,
        [
            _text_event("first", "u1", 1_700_000_123_456),
            _text_event("second", "u2", 1_700_000_124_789),
        ],
        send_async,
        wrapped=wrapped,
    )

    assert await line_main.handle_callback(request) == "OK"

    assert send_async.await_count == 2
    commands = [call.args[0] for call in send_async.await_args_list]
    assert all(isinstance(command, SaveLineChatCommand) for command in commands)
    assert [
        (command.content, command.external_sender_id, command.occurred_at)
        for command in commands
    ] == [
        ("first", "u1", datetime(2023, 11, 14, 22, 15, 23, 456000, tzinfo=UTC)),
        ("second", "u2", datetime(2023, 11, 14, 22, 15, 24, 789000, tzinfo=UTC)),
    ]
    api.reply_message.assert_not_awaited()


@pytest.mark.anyio
@pytest.mark.parametrize("ignored_type", ["follow", "image"])
async def test_handle_callback_ignored_event_does_not_hide_text(
    monkeypatch: pytest.MonkeyPatch, ignored_type: str
) -> None:
    """Non-message events and unsupported messages do not end the batch."""
    line_main = _load_line_main(monkeypatch)
    payload: dict[str, object] = {
        "type": ignored_type if ignored_type == "follow" else "message",
        "source": {"type": "user", "userId": "ignored-user"},
        "replyToken": "ignored-reply",
        "timestamp": 1_700_000_000_000,
        "mode": "active",
        "webhookEventId": "ignored-event",
        "deliveryContext": {"isRedelivery": False},
    }
    if ignored_type == "follow":
        payload["follow"] = {"isUnblocked": False}
        ignored = FollowEvent.from_dict(payload)
    else:
        payload["message"] = {
            "type": "image",
            "id": "image-1",
            "contentProvider": {"type": "line"},
            "quoteToken": "quote-image",
        }
        ignored = MessageEvent.from_dict(payload)
    assert ignored is not None
    send_async = AsyncMock(return_value=Ok(None))
    request, api = _batch_request(
        monkeypatch,
        line_main,
        [ignored, _text_event("after ignored", "u2", 1_700_000_124_789)],
        send_async,
    )

    assert await line_main.handle_callback(request) == "OK"

    send_async.assert_awaited_once()
    command = send_async.await_args_list[0].args[0]
    assert isinstance(command, SaveLineChatCommand)
    assert command.content == "after ignored"
    assert command.external_sender_id == "u2"
    api.reply_message.assert_not_awaited()


@pytest.mark.anyio
async def test_handle_callback_empty_batch(monkeypatch: pytest.MonkeyPatch) -> None:
    """An empty batch succeeds without saving or replying."""
    line_main = _load_line_main(monkeypatch)
    send_async = AsyncMock(return_value=Ok(None))
    request, api = _batch_request(monkeypatch, line_main, [], send_async)

    assert await line_main.handle_callback(request) == "OK"

    send_async.assert_not_awaited()
    api.reply_message.assert_not_awaited()


@pytest.mark.anyio
async def test_handle_callback_save_error_stops_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed save replies once and leaves subsequent events unhandled."""
    line_main = _load_line_main(monkeypatch)
    send_async = AsyncMock(
        return_value=Err(UseCaseError(type=ErrorType.UNEXPECTED, message="save failed"))
    )
    request, api = _batch_request(
        monkeypatch,
        line_main,
        [
            _text_event("fails", "u1", 1_700_000_123_456),
            _text_event("must not save", "u2", 1_700_000_124_789),
        ],
        send_async,
    )

    assert await line_main.handle_callback(request) is None

    send_async.assert_awaited_once()
    command = send_async.await_args_list[0].args[0]
    assert isinstance(command, SaveLineChatCommand)
    assert command.content == "fails"
    api.reply_message.assert_awaited_once()
    reply = api.reply_message.await_args_list[0].args[0]
    assert reply.reply_token == "reply-u1"
    assert len(reply.messages) == 1
    assert reply.messages[0].text == "メッセージの保存に失敗しました。"
