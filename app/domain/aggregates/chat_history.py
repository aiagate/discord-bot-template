from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.value_objects import ChatMessageId, ChatRole, SentAt


@dataclass
class ChatMessage:
    """Chat message entity."""

    _id: ChatMessageId = field(init=False)
    _role: ChatRole
    _content: str
    _sent_at: SentAt

    @classmethod
    def create(cls, role: ChatRole, content: str, sent_at: SentAt) -> ChatMessage:
        """Create a new chat message."""
        instance = cls(
            _role=role,
            _content=content,
            _sent_at=sent_at,
        )
        instance._id = ChatMessageId.generate().expect(
            "ChatMessageId.generate should succeed"
        )
        return instance

    @property
    def id(self) -> ChatMessageId:
        return self._id

    @property
    def role(self) -> ChatRole:
        return self._role

    @property
    def content(self) -> str:
        return self._content

    @property
    def sent_at(self) -> SentAt:
        return self._sent_at
