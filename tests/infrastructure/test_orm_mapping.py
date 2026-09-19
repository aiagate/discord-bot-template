"""Tests for explicit ORM mapping registration and dispatch."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import pytest
from sqlmodel import SQLModel

from app.infrastructure.orm_mapping import ORMMappingRegistry, register_orm_mapping


@dataclass(frozen=True)
class Dummy:
    """Domain fixture whose field differs from its persistence column."""

    name: str


class DummyORM(SQLModel):
    """Persistence fixture with an explicitly mapped column."""

    stored_name: str


def dummy_to_orm(entity: Dummy) -> DummyORM:
    """Map the domain name to its persistence column."""
    return DummyORM(stored_name=entity.name)


def dummy_from_orm(row: SQLModel) -> Dummy:
    """Restore the domain name from its persistence column."""
    assert isinstance(row, DummyORM)
    return Dummy(name=row.stored_name)


@pytest.fixture(autouse=True)
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep registration tests independent of application mappings."""
    monkeypatch.setattr(ORMMappingRegistry, "_domain_to_orm", {})
    monkeypatch.setattr(ORMMappingRegistry, "_to_orm", {})
    monkeypatch.setattr(ORMMappingRegistry, "_from_orm", {})


def test_explicit_mapping_round_trip() -> None:
    """Registration selects both explicit converters despite different fields."""
    register_orm_mapping(Dummy, DummyORM, dummy_to_orm, dummy_from_orm)
    entity = Dummy(name="test")

    row = ORMMappingRegistry.to_orm(entity)

    assert ORMMappingRegistry.get_orm_type(Dummy) is DummyORM
    assert isinstance(row, DummyORM)
    assert row.stored_name == "test"
    assert ORMMappingRegistry.from_orm(row) == entity


def test_mapping_dictionary_is_a_copy() -> None:
    """Changing the returned mapping dictionary cannot unregister a mapping."""
    register_orm_mapping(Dummy, DummyORM, dummy_to_orm, dummy_from_orm)

    mappings = ORMMappingRegistry.get_mapping_dict()
    assert mappings == {Dummy: DummyORM}
    mappings.clear()

    assert ORMMappingRegistry.get_orm_type(Dummy) is DummyORM


def test_identical_registration_is_idempotent() -> None:
    register_orm_mapping(Dummy, DummyORM, dummy_to_orm, dummy_from_orm)
    register_orm_mapping(Dummy, DummyORM, dummy_to_orm, dummy_from_orm)

    assert ORMMappingRegistry.get_mapping_dict() == {Dummy: DummyORM}


@pytest.mark.parametrize("conflict", ["domain", "orm", "to_orm", "from_orm"])
def test_conflicting_registration_preserves_both_directions(conflict: str) -> None:
    class OtherDomain:
        pass

    class OtherORM(SQLModel):
        pass

    register_orm_mapping(Dummy, DummyORM, dummy_to_orm, dummy_from_orm)

    with pytest.raises(ValueError, match="Conflicting"):
        register_orm_mapping(
            OtherDomain if conflict == "domain" else Dummy,
            OtherORM if conflict == "orm" else DummyORM,
            (lambda _: DummyORM(stored_name="wrong"))
            if conflict == "to_orm"
            else dummy_to_orm,
            (lambda _: Dummy(name="wrong"))
            if conflict == "from_orm"
            else dummy_from_orm,
        )

    original = Dummy(name="original")
    row = ORMMappingRegistry.to_orm(original)
    assert isinstance(row, DummyORM)
    assert row.stored_name == original.name
    assert ORMMappingRegistry.from_orm(row) == original
    assert ORMMappingRegistry.get_mapping_dict() == {Dummy: DummyORM}
    with pytest.raises(ValueError, match="No ORM mapping registered"):
        ORMMappingRegistry.to_orm(OtherDomain())
    with pytest.raises(ValueError, match="No domain mapping registered"):
        ORMMappingRegistry.from_orm(OtherORM())


def test_unregistered_domain_raises_error() -> None:
    """Unregistered domain types have no implicit conversion."""
    assert ORMMappingRegistry.get_orm_type(Dummy) is None
    with pytest.raises(ValueError, match="No ORM mapping registered.*Dummy"):
        ORMMappingRegistry.to_orm(Dummy(name="test"))


def test_unregistered_orm_raises_error() -> None:
    """Unregistered persistence types have no implicit conversion."""
    with pytest.raises(ValueError, match="No domain mapping registered.*DummyORM"):
        ORMMappingRegistry.from_orm(DummyORM(stored_name="test"))


@pytest.mark.parametrize("missing_mapper", ["to_orm", "from_orm"])
def test_registration_requires_both_mappers(missing_mapper: str) -> None:
    """Omitting either mapper fails before registering the pair."""
    mappers: dict[str, Any] = {
        "to_orm": dummy_to_orm,
        "from_orm": dummy_from_orm,
    }
    del mappers[missing_mapper]

    with pytest.raises(TypeError, match=missing_mapper):
        register_orm_mapping(Dummy, DummyORM, **mappers)

    assert ORMMappingRegistry.get_mapping_dict() == {}


@pytest.mark.parametrize("invalid_mapper", ["to_orm", "from_orm"])
@pytest.mark.parametrize("already_registered", [False, True])
def test_invalid_registration_preserves_state(
    invalid_mapper: str, already_registered: bool
) -> None:
    """Invalid converters cannot create or partially replace a registration."""
    if already_registered:
        register_orm_mapping(Dummy, DummyORM, dummy_to_orm, dummy_from_orm)

    def replacement_to_orm(entity: Dummy) -> SQLModel:
        return DummyORM(stored_name="replacement")

    def replacement_from_orm(row: SQLModel) -> Dummy:
        return Dummy(name="replacement")

    mappers: dict[str, Any] = {
        "to_orm": replacement_to_orm,
        "from_orm": replacement_from_orm,
    }
    mappers[invalid_mapper] = None

    with pytest.raises(TypeError, match="Both to_orm and from_orm must be callable"):
        register_orm_mapping(Dummy, DummyORM, **mappers)

    if already_registered:
        entity = Dummy(name="original")
        row = ORMMappingRegistry.to_orm(entity)
        assert isinstance(row, DummyORM)
        assert row.stored_name == "original"
        assert ORMMappingRegistry.from_orm(row) == entity
    else:
        assert ORMMappingRegistry.get_mapping_dict() == {}
        with pytest.raises(ValueError, match="No ORM mapping registered"):
            ORMMappingRegistry.to_orm(Dummy(name="test"))
        with pytest.raises(ValueError, match="No domain mapping registered"):
            ORMMappingRegistry.from_orm(DummyORM(stored_name="test"))


@pytest.mark.parametrize("direction", ["to_orm", "from_orm"])
def test_mapper_errors_propagate(direction: str) -> None:
    """Mapping failures reach the caller without conversion or suppression."""
    failure = ValueError("invalid persisted value")

    def fail(value: Any) -> Any:
        raise failure

    to_orm: Callable[[Any], SQLModel] = fail if direction == "to_orm" else dummy_to_orm
    from_orm: Callable[[SQLModel], Any] = (
        fail if direction == "from_orm" else dummy_from_orm
    )
    register_orm_mapping(Dummy, DummyORM, to_orm, from_orm)

    with pytest.raises(ValueError) as exc_info:
        if direction == "to_orm":
            ORMMappingRegistry.to_orm(Dummy(name="test"))
        else:
            ORMMappingRegistry.from_orm(DummyORM(stored_name="test"))

    assert exc_info.value is failure
