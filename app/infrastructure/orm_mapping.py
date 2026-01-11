"""Automatic ORM mapping registry with decorator-based registration."""

import inspect
import logging
from dataclasses import fields, is_dataclass
from typing import Any, ClassVar, TypeVar, cast, get_args, get_origin, get_type_hints

from sqlmodel import SQLModel

from app.core.result import Result, is_err, is_ok
from app.domain.interfaces import IValueObject

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _get_entity_properties(entity_type: type) -> dict[str, property]:
    """Get all properties defined on an entity class.

    Returns a dictionary mapping property name to property object.
    Excludes dunder properties (starting with __).
    """
    return {
        name: obj
        for name, obj in inspect.getmembers(entity_type)
        if isinstance(obj, property) and not name.startswith("__")
    }


def entity_to_orm_dict(entity: Any) -> dict[str, Any]:
    """Convert domain entity to dictionary for ORM model creation.

    Automatically converts IValueObject fields to primitive types.

    Args:
        entity: Domain entity instance (must be a dataclass)

    Returns:
        Dictionary with primitive values suitable for ORM model

    Raises:
        TypeError: If entity is not a dataclass

    Example:
        >>> user = User(id=UserId(...), email=Email("test@example.com"), ...)
        >>> entity_to_orm_dict(user)
        {'id': '01ARZ3NDEK...', 'email': 'test@example.com', ...}
    """
    if not is_dataclass(entity):
        raise TypeError(f"Expected dataclass, got {type(entity).__name__}")

    result: dict[str, Any] = {}
    entity_type = type(entity)

    # Check if entity has properties (like Team with _id -> id property)
    properties = _get_entity_properties(entity_type)

    if properties:
        # Property-based entity (Team pattern)
        # Use property names as ORM column names
        for name in properties:
            field_value = getattr(entity, name)

            if isinstance(field_value, IValueObject):
                result[name] = field_value.to_primitive()
            else:
                result[name] = field_value
    else:
        # Field-based entity (User pattern - legacy)
        # Use dataclass field names directly
        for field in fields(entity):
            field_value = getattr(entity, field.name)

            if isinstance(field_value, IValueObject):
                result[field.name] = field_value.to_primitive()
            else:
                result[field.name] = field_value

    return result


def _build_field_to_property_mapping(entity_type: type) -> dict[str, str]:
    """Build mapping from private field names to property names.

    For entities with private fields (e.g., _id) and corresponding properties
    (e.g., id), builds a mapping from field name to property name.

    Returns:
        Dictionary mapping field name to property name (e.g., {"_id": "id"}).
    """
    properties = _get_entity_properties(entity_type)
    property_names = set(properties.keys())

    mapping: dict[str, str] = {}
    for field in fields(entity_type):
        field_name = field.name
        # Check if field name starts with _ and has corresponding property
        if field_name.startswith("_"):
            public_name = field_name[1:]  # Remove leading underscore
            if public_name in property_names:
                mapping[field_name] = public_name

    return mapping


def _convert_orm_value_to_field_value(
    orm_value: Any,
    field_type: type,
    field_name: str,
) -> Any:
    """Convert an ORM value to the appropriate field value.

    Handles IValueObject conversion and Optional types.
    """
    # Check if the field type is Optional (Union with None)
    origin = get_origin(field_type)
    args = get_args(field_type)

    # Check if it's a Union type and contains NoneType
    is_optional = origin is not None and type(None) in args
    actual_type = field_type

    if is_optional:
        # Extract the non-None type from Optional[T]
        non_none_types = [arg for arg in args if arg is not type(None)]
        if non_none_types:
            actual_type = non_none_types[0]

    # Check if the actual type implements IValueObject
    if hasattr(actual_type, "from_primitive") and callable(actual_type.from_primitive):
        # Special handling for None values
        if orm_value is None:
            if is_optional:
                return None
            elif field_name.lstrip("_") == "id" and hasattr(actual_type, "generate"):
                # For non-Optional ID fields, generate a new ID
                id_result = actual_type.generate()
                if is_err(id_result):
                    raise ValueError(f"Failed to generate ID: {id_result.error}")
                assert is_ok(id_result)  # type: ignore[reportAssertType]
                return id_result.unwrap()
            else:
                raise ValueError(
                    f"Field '{field_name}' is None but "
                    f"{actual_type.__name__} is not Optional and has no "
                    f"generate() method"
                )
        else:
            # Convert from primitive using from_primitive()
            result = cast(Result[Any, Any], actual_type.from_primitive(orm_value))
            if is_err(result):
                raise ValueError(
                    f"Failed to convert field '{field_name}' "
                    f"from primitive: {result.error}"
                )
            assert is_ok(result)  # type: ignore[reportAssertType]
            return result.unwrap()
    else:
        # Use primitive value as-is
        return orm_value


def orm_to_entity[T](orm_instance: SQLModel, entity_type: type[T]) -> T:
    """Convert ORM model to domain entity.

    Automatically converts primitive fields to IValueObject instances
    based on type annotations.

    For property-based entities with init=False fields, values are set
    directly using object.__setattr__ after initial construction.

    Args:
        orm_instance: ORM model instance
        entity_type: Target domain entity class (must be a dataclass)

    Returns:
        Domain entity instance

    Raises:
        TypeError: If entity_type is not a dataclass
        ValueError: If conversion fails

    Example:
        >>> user_orm = UserORM(id='01ARZ3NDEK...', email='test@example.com')
        >>> user = orm_to_entity(user_orm, User)
        >>> assert isinstance(user.id, UserId)
        >>> assert isinstance(user.email, Email)
    """
    if not is_dataclass(entity_type):
        raise TypeError(f"Expected dataclass, got {entity_type.__name__}")

    # Get type hints from the entity class
    type_hints = get_type_hints(entity_type)

    # Build mapping from private field names to property names
    field_to_property = _build_field_to_property_mapping(entity_type)

    init_kwargs: dict[str, Any] = {}
    non_init_values: dict[str, Any] = {}

    for field in fields(entity_type):
        field_name = field.name
        field_type = type_hints.get(field_name)

        if field_type is None:
            raise ValueError(
                f"No type annotation found for field '{field_name}' "
                f"in {entity_type.__name__}"
            )

        # Determine ORM column name
        # For property-based entities, use the property name (e.g., "id" not "_id")
        orm_column_name = field_to_property.get(field_name, field_name)

        # Get the value from ORM instance
        orm_value = getattr(orm_instance, orm_column_name, None)

        # Convert the value
        converted_value = _convert_orm_value_to_field_value(
            orm_value, field_type, field_name
        )

        # Separate init and non-init fields
        if field.init:
            init_kwargs[field_name] = converted_value
        else:
            non_init_values[field_name] = converted_value

    # Create entity with init fields only
    entity = entity_type(**init_kwargs)

    # Set non-init fields directly (for init=False fields like Team._id)
    for field_name, value in non_init_values.items():
        object.__setattr__(entity, field_name, value)

    return entity


class ORMMappingRegistry:
    """Registry for domain-to-ORM mapping with automatic conversion.

    This class maintains bidirectional mappings between domain aggregates
    and their corresponding ORM models, using automatic conversion based
    on IValueObject protocol.
    """

    _domain_to_orm: ClassVar[dict[type, type[SQLModel]]] = {}

    @classmethod
    def register(
        cls,
        domain_type: type,
        orm_type: type[SQLModel],
    ) -> None:
        """Register a domain-ORM mapping pair.

        Args:
            domain_type: Domain aggregate class (e.g., User, Team)
            orm_type: ORM model class (e.g., UserORM, TeamORM)
        """
        cls._domain_to_orm[domain_type] = orm_type
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
        """Convert domain instance to ORM model using automatic conversion.

        Args:
            domain_instance: Domain aggregate instance

        Returns:
            ORM model instance

        Raises:
            ValueError: If domain type is not registered
        """
        domain_type = type(domain_instance)
        orm_type = cls._domain_to_orm.get(domain_type)

        if orm_type is None:
            raise ValueError(
                f"No ORM mapping registered for domain type: {domain_type.__name__}"
            )

        # Use automatic conversion
        orm_dict = entity_to_orm_dict(domain_instance)
        return orm_type(**orm_dict)

    @classmethod
    def from_orm(cls, orm_instance: SQLModel) -> Any:
        """Convert ORM model to domain instance using automatic conversion.

        Args:
            orm_instance: ORM model instance

        Returns:
            Domain aggregate instance

        Raises:
            ValueError: If ORM type is not registered
        """
        # Find domain type by ORM type
        orm_type = type(orm_instance)
        for domain_type, registered_orm_type in cls._domain_to_orm.items():
            if registered_orm_type == orm_type:
                # Use automatic conversion
                return orm_to_entity(orm_instance, domain_type)

        raise ValueError(
            f"No domain mapping registered for ORM type: {orm_type.__name__}"
        )

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
) -> None:
    """Register ORM mapping for a domain type.

    This is a convenience function for registering mappings without
    needing to provide conversion functions (automatic conversion is used).

    Args:
        domain_type: Domain aggregate class
        orm_type: ORM model class

    Example:
        >>> from app.domain.aggregates.user import User
        >>> from app.infrastructure.orm_models.user_orm import UserORM
        >>> register_orm_mapping(User, UserORM)
    """
    ORMMappingRegistry.register(domain_type, orm_type)
