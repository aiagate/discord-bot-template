"""LLM timestamp formatting leaves stored UTC values unchanged."""

from datetime import UTC, datetime, timedelta, timezone

import pytest

from app.contracts.messages.character_prompt import prompt_datetime, prompt_message
from app.domain.aggregates.chat_message import ChatMessage
from app.domain.value_objects import MessageContent


@pytest.mark.parametrize(
    ("timestamp", "expected"),
    [
        (
            datetime(2026, 9, 12, 7, 12, 36, 825114, tzinfo=UTC),
            "2026-09-12 16:12:36 JST",
        ),
        (
            datetime(2026, 9, 12, 15, 0, tzinfo=UTC),
            "2026-09-13 00:00:00 JST",
        ),
        (
            datetime(2026, 12, 31, 15, 0, tzinfo=UTC),
            "2027-01-01 00:00:00 JST",
        ),
        (
            datetime(2026, 9, 12, 16, 12, 36, tzinfo=timezone(timedelta(hours=9))),
            "2026-09-12 16:12:36 JST",
        ),
        (
            datetime(2026, 9, 12, 0, 12, 36, tzinfo=timezone(timedelta(hours=-7))),
            "2026-09-12 16:12:36 JST",
        ),
    ],
)
def test_prompt_datetime_converts_the_instant_to_jst(
    timestamp: datetime, expected: str
) -> None:
    assert prompt_datetime(timestamp) == expected


def test_prompt_datetime_rejects_a_missing_timezone() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        prompt_datetime(datetime(2026, 9, 12, 7, 12))


def test_prompt_message_formats_only_the_outgoing_timestamp() -> None:
    occurred_at = datetime(2026, 12, 31, 15, 0, 1, 123456, tzinfo=UTC)
    message = ChatMessage.create_discord(
        guild_id="456",
        channel_id="123",
        external_sender_id="alice",
        external_message_id="100",
        reply_to_external_message_id="99",
        content=MessageContent.text("元の本文"),
        occurred_at=occurred_at,
    )

    payload = prompt_message(message, "表示する本文")

    assert payload["occurred_at"] == "2027-01-01 00:00:01 JST"
    assert payload["content"] == "表示する本文"
    assert payload["message_id"] == "100"
    assert payload["reply_to_message_id"] == "99"
    assert message.occurred_at == occurred_at
    assert message.occurred_at.tzinfo is UTC
    assert message.occurred_at.microsecond == 123456
    assert message.content.payload["text"] == "元の本文"
