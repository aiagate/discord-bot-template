from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, auto
from typing import Any


class EventType(Enum):
    USER_MESSAGE = auto()
    SNS_UPDATE = auto()
    HEARTBEAT = auto()


@dataclass(frozen=True)
class AppEvent:
    type: EventType
    payload: dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)
