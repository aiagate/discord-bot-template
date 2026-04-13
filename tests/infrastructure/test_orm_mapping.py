"""Tests for ORM mapping registry with automatic conversion."""

from dataclasses import dataclass
from datetime import UTC, datetime

import pytest
from flow_res import Ok, Result
from sqlmodel import Field, SQLModel

from app.infrastructure.orm_mapping import (
    ORMMappingRegistry,
    entity_to_orm_dict,
    orm_to_entity,
    register_orm_mapping,
)

# Test fixtures


@dataclass(frozen=True)
class DummyId:
    """Dummy ID value object for testing."""

    _value: str

    def to_primitive(self) -> str:
        return self._value

    @classmethod
    def from_primitive(cls, value: str) -> Result["DummyId", ValueError]:
        return Ok(cls(_value=value))

    @classmethod
    def generate(cls) -> Result["DummyId", ValueError]:
        return Ok(cls(_value="generated-id"))


@dataclass(frozen=True)
class DummyEmail:
    """Dummy email value object for testing."""

    _value: str

    def to_primitive(self) -> str:
        return self._value

    @classmethod
    def from_primitive(cls, value: str) -> Result["DummyEmail", ValueError]:
        return Ok(cls(_value=value))


class DummyORM(SQLModel, table=True):  # type: ignore[call-arg]
    """Dummy ORM model for testing."""

    __tablename__ = "dummies"  # type: ignore[reportAssignmentType]
    id: str | None = Field(default=None, primary_key=True)
    name: str
    email: str
    created_at: datetime


@dataclass
class Dummy:
    """Dummy domain class for testing."""

    id: DummyId
    name: str
    email: DummyEmail
    created_at: datetime


# Tests


def test_entity_to_orm_dict_converts_value_objects() -> None:
    """Test that entity_to_orm_dict converts IValueObject fields to primitives."""
    dummy = Dummy(
        id=DummyId("test-id"),
        name="Test Name",
        email=DummyEmail("test@example.com"),
        created_at=datetime.now(UTC),
    )

    result = entity_to_orm_dict(dummy)

    assert result["id"] == "test-id"
    assert result["name"] == "Test Name"
    assert result["email"] == "test@example.com"
    assert isinstance(result["created_at"], datetime)


def test_entity_to_orm_dict_raises_for_non_dataclass() -> None:
    """Test that entity_to_orm_dict raises TypeError for non-dataclass."""

    class NotADataclass:
        pass

    with pytest.raises(TypeError, match="Expected dataclass"):
        entity_to_orm_dict(NotADataclass())


def test_orm_to_entity_converts_to_value_objects() -> None:
    """Test that orm_to_entity converts primitives to IValueObject instances."""
    now = datetime.now(UTC)
    orm = DummyORM(
        id="test-id", name="Test Name", email="test@example.com", created_at=now
    )

    result = orm_to_entity(orm, Dummy)

    assert isinstance(result, Dummy)
    assert isinstance(result.id, DummyId)
    assert result.id.to_primitive() == "test-id"
    assert result.name == "Test Name"
    assert isinstance(result.email, DummyEmail)
    assert result.email.to_primitive() == "test@example.com"
    assert result.created_at == now


def test_orm_to_entity_generates_id_when_none() -> None:
    """Test that orm_to_entity generates ID when ORM id is None."""
    now = datetime.now(UTC)
    orm = DummyORM(id=None, name="Test", email="test@example.com", created_at=now)

    result = orm_to_entity(orm, Dummy)

    assert isinstance(result.id, DummyId)
    assert result.id.to_primitive() == "generated-id"


def test_orm_to_entity_raises_for_non_dataclass() -> None:
    """Test that orm_to_entity raises TypeError for non-dataclass."""
    orm = DummyORM(
        id="test", name="Test", email="test@example.com", created_at=datetime.now(UTC)
    )

    class NotADataclass:
        pass

    with pytest.raises(TypeError, match="Expected dataclass"):
        orm_to_entity(orm, NotADataclass)  # type: ignore[arg-type]


def test_register_orm_mapping() -> None:
    """Test manual registration of domain-ORM mapping."""
    register_orm_mapping(Dummy, DummyORM)
    assert ORMMappingRegistry.get_orm_type(Dummy) == DummyORM


def test_registry_to_orm_with_automatic_conversion() -> None:
    """Test registry to_orm with automatic conversion."""
    register_orm_mapping(Dummy, DummyORM)

    dummy = Dummy(
        id=DummyId("test-id"),
        name="Test",
        email=DummyEmail("test@example.com"),
        created_at=datetime.now(UTC),
    )

    orm = ORMMappingRegistry.to_orm(dummy)

    assert isinstance(orm, DummyORM)
    assert orm.id == "test-id"
    assert orm.name == "Test"
    assert orm.email == "test@example.com"


def test_registry_from_orm_with_automatic_conversion() -> None:
    """Test registry from_orm with automatic conversion."""
    register_orm_mapping(Dummy, DummyORM)

    now = datetime.now(UTC)
    orm = DummyORM(id="test-id", name="Test", email="test@example.com", created_at=now)

    dummy = ORMMappingRegistry.from_orm(orm)

    assert isinstance(dummy, Dummy)
    assert isinstance(dummy.id, DummyId)
    assert dummy.id.to_primitive() == "test-id"
    assert isinstance(dummy.email, DummyEmail)
    assert dummy.email.to_primitive() == "test@example.com"


def test_unregistered_type_raises_error() -> None:
    """Test that unregistered type raises ValueError."""

    @dataclass
    class UnregisteredDummy:
        id: str

    dummy = UnregisteredDummy(id="test")

    with pytest.raises(ValueError, match="No ORM mapping registered"):
        ORMMappingRegistry.to_orm(dummy)
