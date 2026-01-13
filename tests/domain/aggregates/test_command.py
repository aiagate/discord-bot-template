from datetime import UTC, datetime
from uuid import uuid4

from app.domain.aggregates.command import Command


def test_command_initialization():
    """Test Command initialization."""
    cmd_id = uuid4()
    cmd_type = "TEST_COMMAND"
    payload = {"key": "value"}
    created_at = datetime.now(UTC)
    status = "PENDING"

    command = Command(
        id=cmd_id,
        type=cmd_type,
        payload=payload,
        created_at=created_at,
        status=status,
    )

    assert command.id == cmd_id
    assert command.type == cmd_type
    assert command.payload == payload
    assert command.created_at == created_at
    assert command.status == status
    assert command.processed_at is None
