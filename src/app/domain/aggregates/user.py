from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime

from app.domain.value_objects import DisplayName, Email, UserId, Version


@dataclass(kw_only=True, slots=True)
class User:
    """User aggregate root.

    Implements IAuditable: timestamps are infrastructure concerns but exposed
    as read-only fields for auditing and display purposes. The repository layer
    automatically manages created_at and updated_at.

    Implements IVersionable: optimistic locking via version field, which is
    automatically managed by the repository layer during updates.
    """

    _id: UserId = field(
        init=False,
        default_factory=lambda: UserId.generate().expect(
            "UserId.generate should succeed"
        ),
    )
    _display_name: DisplayName
    _email: Email
    _version: Version = field(init=False, default_factory=lambda: Version(0))
    _created_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))
    _updated_at: datetime = field(init=False, default_factory=lambda: datetime.now(UTC))

    @classmethod
    def register(cls, display_name: DisplayName, email: Email) -> User:
        """ユーザーを登録するファクトリメソッド"""
        return User(_display_name=display_name, _email=email)

    @property
    def id(self) -> UserId:
        return self._id

    @property
    def display_name(self) -> DisplayName:
        return self._display_name

    @property
    def email(self) -> Email:
        return self._email

    @property
    def version(self) -> Version:
        return self._version

    @property
    def created_at(self) -> datetime:
        return self._created_at

    @property
    def updated_at(self) -> datetime:
        return self._updated_at

    def change_email(self, new_email: Email) -> User:
        """メールアドレスを変更するドメインロジック

        Note: updated_at is automatically managed by the repository layer.
        """
        self._email = new_email

        return self
