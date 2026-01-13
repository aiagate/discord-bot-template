from datetime import UTC, datetime, timedelta

import pytest
from freezegun import freeze_time

from app.core.result import is_err
from app.domain.aggregates.chat_history import ChatMessage
from app.domain.value_objects import ChatRole, SentAt


class TestChatMessage:
    def test_create(self):
        role = ChatRole.USER
        content = "test content"
        raw_sent_at = datetime.now(UTC)
        sent_at = SentAt.from_primitive(raw_sent_at).expect("Failed to create SentAt")

        message = ChatMessage.create(role=role, content=content, sent_at=sent_at)

        assert message.role == role
        assert message.content == content
        assert message.id is not None
        assert message.sent_at == sent_at
        assert message.sent_at.to_primitive() == raw_sent_at


class TestSentAt:
    @freeze_time("2024-01-01 12:00:00")
    @pytest.mark.parametrize(
        "seconds_ago, expected_text",
        [
            (30, "just now"),
            (59, "just now"),
            (60, "1 minute ago"),
            (119, "1 minute ago"),
            (120, "2 minutes ago"),
            (3599, "59 minutes ago"),
            (3600, "1 hour ago"),
            (7199, "1 hour ago"),
            (7200, "2 hours ago"),
            (86399, "23 hours ago"),
            (86400, "1 day ago"),
            (172799, "1 day ago"),
            (172800, "2 days ago"),
            (604799, "6 days ago"),
            (604800, "1 week ago"),
            (1209599, "1 week ago"),
            (1209600, "2 weeks ago"),
        ],
    )
    def test_display_time(self, seconds_ago: int, expected_text: str):
        # Current time is frozen at 2024-01-01 12:00:00
        now = datetime.now(UTC)
        past_time = now - timedelta(seconds=seconds_ago)

        # Create SentAt.
        sent_at = SentAt.from_primitive(past_time).expect("Should create SentAt")

        # The property access calls datetime.now(UTC) which is frozen
        assert sent_at.display_time == expected_text

    def test_creation_validation(self):
        # Test offset-naive handling
        # freezegun might intefere with datetime.now() if active, but here it's separate test method (not decorated)
        # However, to be safe, we can use specific time.
        naive = datetime(2023, 1, 1, 12, 0, 0)

        sent_at = SentAt.from_primitive(naive).expect("Should accept naive and convert")

        # Check if it became aware
        assert sent_at.to_primitive().tzinfo == UTC
        # Check conversion (assuming local time if system specific, or UTC if simplistic replacement)
        # The implementation uses .replace(tzinfo=UTC), so the hour labels remain same.
        assert sent_at.to_primitive().year == 2023
        assert sent_at.to_primitive().hour == 12

        # Test invalid type
        result = SentAt.from_primitive("not a datetime")  # type: ignore
        assert is_err(result)
