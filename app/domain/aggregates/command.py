from dataclasses import dataclass
from datetime import datetime
from typing import Any
from uuid import UUID


@dataclass
class Command:
    """Represents a command to be executed by the bot."""

    id: UUID
    type: str
    payload: dict[str, Any]
    created_at: datetime
    status: str
    processed_at: datetime | None = None
