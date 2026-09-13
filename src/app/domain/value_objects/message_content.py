"""Message content value object."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from flow_res import Err, Ok, Result


class MessageContentType(StrEnum):
    """Supported message content types."""

    TEXT = "TEXT"
    IMAGE = "IMAGE"
    STICKER = "STICKER"
    EMOJI = "EMOJI"


@dataclass(frozen=True, slots=True)
class MessageContent:
    """Content payload for a single chat message.

    The payload shape is intentionally flexible because each provider exposes
    different metadata for images, stickers, and emoji.
    """

    _type: MessageContentType
    _payload: dict[str, Any]

    def __post_init__(self) -> None:
        """Copy the complete payload before storing it."""
        object.__setattr__(self, "_payload", deepcopy(self._payload))

    @classmethod
    def text(cls, text: str) -> MessageContent:
        """Create text message content."""
        return cls(_type=MessageContentType.TEXT, _payload={"text": text})

    @property
    def type(self) -> MessageContentType:
        """Return the message content type."""
        return self._type

    @property
    def payload(self) -> dict[str, Any]:
        """Return an independent copy of the message content payload."""
        return deepcopy(self._payload)

    @classmethod
    def from_primitive(
        cls,
        value: dict[str, Any],
    ) -> Result[MessageContent, Exception]:
        """Create message content from a persistence payload."""
        content_type = value.get("type")
        payload = value.get("payload")

        if not isinstance(content_type, str):
            return Err(ValueError("Message content type must be a string."))
        if not isinstance(payload, dict):
            return Err(ValueError("Message content payload must be a dictionary."))

        try:
            normalized_type = MessageContentType(content_type.upper())
        except ValueError:
            return Err(ValueError(f"Invalid message content type: {content_type}"))

        return Ok(cls(_type=normalized_type, _payload=payload))

    def to_primitive(self) -> dict[str, Any]:
        """Convert message content to a persistence payload."""
        return {
            "type": self._type.value,
            "payload": deepcopy(self._payload),
        }
