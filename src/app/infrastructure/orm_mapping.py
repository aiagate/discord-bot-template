"""Registry for explicit domain-to-ORM mappings."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any, ClassVar

from sqlmodel import SQLModel

logger = logging.getLogger(__name__)


class ORMMappingRegistry:
    """Register and select explicit bidirectional domain-to-ORM mappers."""

    _domain_to_orm: ClassVar[dict[type, type[SQLModel]]] = {}
    _to_orm: ClassVar[dict[type, Callable[[Any], SQLModel]]] = {}
    _from_orm: ClassVar[dict[type[SQLModel], Callable[[SQLModel], Any]]] = {}

    @classmethod
    def register(
        cls,
        domain_type: type,
        orm_type: type[SQLModel],
        to_orm: Callable[[Any], SQLModel],
        from_orm: Callable[[SQLModel], Any],
    ) -> None:
        """Register a domain-ORM mapping pair.

        Args:
            domain_type: Domain aggregate class (e.g., User, Team)
            orm_type: ORM model class (e.g., UserORM, TeamORM)
            to_orm: Explicit domain-to-ORM converter
            from_orm: Explicit ORM-to-domain converter

        Raises:
            TypeError: If either converter is not callable
            ValueError: If either type already has a different mapping
        """
        if not callable(to_orm) or not callable(from_orm):
            raise TypeError("Both to_orm and from_orm must be callable.")

        if domain_type in cls._domain_to_orm:
            if (
                cls._domain_to_orm[domain_type] is orm_type
                and cls._to_orm[domain_type] is to_orm
                and cls._from_orm[orm_type] is from_orm
            ):
                return
            raise ValueError(
                f"Conflicting ORM mapping for domain type: {domain_type.__name__}"
            )
        if orm_type in cls._from_orm:
            raise ValueError(
                f"Conflicting domain mapping for ORM type: {orm_type.__name__}"
            )

        cls._domain_to_orm[domain_type] = orm_type
        cls._to_orm[domain_type] = to_orm
        cls._from_orm[orm_type] = from_orm
        logger.debug(
            f"Registered ORM mapping: {domain_type.__name__} <-> {orm_type.__name__}"
        )

    @classmethod
    def get_orm_type(cls, domain_type: type) -> type[SQLModel] | None:
        """Get ORM type for a domain type.

        Args:
            domain_type: Domain aggregate class

        Returns:
            ORM model class or None if not registered
        """
        return cls._domain_to_orm.get(domain_type)

    @classmethod
    def to_orm(cls, domain_instance: Any) -> SQLModel:
        """Convert domain instance to ORM model using its registered mapper.

        Args:
            domain_instance: Domain aggregate instance

        Returns:
            ORM model instance

        Raises:
            ValueError: If domain type is not registered
        """
        domain_type = type(domain_instance)
        mapper = cls._to_orm.get(domain_type)

        if mapper is None:
            raise ValueError(
                f"No ORM mapping registered for domain type: {domain_type.__name__}"
            )

        return mapper(domain_instance)

    @classmethod
    def from_orm(cls, orm_instance: SQLModel) -> Any:
        """Convert ORM model to domain instance using its registered mapper.

        Args:
            orm_instance: ORM model instance

        Returns:
            Domain aggregate instance

        Raises:
            ValueError: If ORM type is not registered
        """
        orm_type = type(orm_instance)
        mapper = cls._from_orm.get(orm_type)
        if mapper is None:
            raise ValueError(
                f"No domain mapping registered for ORM type: {orm_type.__name__}"
            )

        return mapper(orm_instance)

    @classmethod
    def get_mapping_dict(cls) -> dict[type, type[SQLModel]]:
        """Get the domain-to-ORM mapping dictionary.

        Returns:
            Dictionary mapping domain types to ORM types
        """
        return cls._domain_to_orm.copy()


def register_orm_mapping(
    domain_type: type,
    orm_type: type[SQLModel],
    to_orm: Callable[[Any], SQLModel],
    from_orm: Callable[[SQLModel], Any],
) -> None:
    """Register a domain/ORM pair with both explicit conversion functions."""
    ORMMappingRegistry.register(domain_type, orm_type, to_orm, from_orm)
