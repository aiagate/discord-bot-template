"""Domain interfaces."""

from app.domain.interfaces.auditable import IAuditable
from app.domain.interfaces.value_object import IValueObject
from app.domain.interfaces.versionable import IVersionable

__all__ = ["IAuditable", "IValueObject", "IVersionable"]
