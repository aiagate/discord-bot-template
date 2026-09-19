"""Shared identity, hash, and public-state checks for aggregate samples."""

from dataclasses import FrozenInstanceError, fields

import pytest

from app.domain import aggregates
from app.domain.aggregates import ChatMessage, Team, TeamMembership, User
from app.domain.value_objects import Email, MessageContent, TeamName
from tests.domain.aggregate_cases import (
    AGGREGATE_CASES,
    TRANSITION_EXEMPTIONS,
    Aggregate,
    AggregateCase,
    aggregate_state,
)


@pytest.fixture(
    params=AGGREGATE_CASES, ids=lambda aggregate_type: aggregate_type.__name__
)
def aggregate_sample(request: pytest.FixtureRequest) -> tuple[Aggregate, AggregateCase]:
    aggregate_type: type[Aggregate] = request.param
    case = AGGREGATE_CASES[aggregate_type]
    return aggregate_type.restore(**case.restore_values), case


def test_every_public_aggregate_has_contract_cases() -> None:
    public_types = {getattr(aggregates, name) for name in aggregates.__all__}
    assert set(AGGREGATE_CASES) == public_types
    assert set(TRANSITION_EXEMPTIONS) | {TeamMembership} == public_types
    assert all(TRANSITION_EXEMPTIONS.values())


def test_identity_ignores_state_but_requires_same_concrete_type(
    aggregate_sample: tuple[Aggregate, AggregateCase],
) -> None:
    aggregate, case = aggregate_sample
    same_id = type(aggregate).restore(**(case.restore_values | case.changed_values))
    other_id = type(aggregate.id).generate().expect("valid ID")
    different_id = type(aggregate).restore(
        **(case.restore_values | {case.id_parameter: other_id})
    )
    subclass = type(f"Special{type(aggregate).__name__}", (type(aggregate),), {})
    subtype_instance = subclass.restore(**case.restore_values)

    assert aggregate is not same_id
    assert aggregate_state(aggregate) != aggregate_state(same_id)
    assert aggregate == same_id and same_id == aggregate
    assert aggregate != different_id
    assert aggregate != object()
    assert aggregate != subtype_instance and subtype_instance != aggregate
    if case.mutable:
        with pytest.raises(TypeError, match="unhashable"):
            hash(aggregate)
    else:
        assert hash(aggregate) == hash(same_id)


def test_all_stored_fields_are_in_the_explicit_state_comparison(
    aggregate_sample: tuple[Aggregate, AggregateCase],
) -> None:
    aggregate, case = aggregate_sample
    assert case.invalid_rows
    assert {field.name.removeprefix("_") for field in fields(aggregate)} == set(
        case.state_fields
    )


def test_public_fields_cannot_bypass_domain_operations(
    aggregate_sample: tuple[Aggregate, AggregateCase],
) -> None:
    aggregate, case = aggregate_sample
    before = aggregate_state(aggregate)
    for name in case.state_fields:
        with pytest.raises((AttributeError, TypeError)):
            setattr(aggregate, name, None)
    with pytest.raises(FrozenInstanceError):
        aggregate.id._value = None  # pyright: ignore[reportAttributeAccessIssue]
    assert aggregate_state(aggregate) == before


@pytest.mark.parametrize(
    ("aggregate_type", "operation", "field", "new_value"),
    [
        (User, "change_email", "email", Email("new@example.com")),
        (Team, "change_name", "name", TeamName("New name")),
    ],
)
def test_valid_attribute_change_preserves_identity_and_audit_state(
    aggregate_type: type[User] | type[Team],
    operation: str,
    field: str,
    new_value: object,
) -> None:
    aggregate = aggregate_type.restore(**AGGREGATE_CASES[aggregate_type].restore_values)
    before = aggregate_state(aggregate)

    result = getattr(aggregate, operation)(new_value)

    assert result is aggregate
    assert aggregate_state(aggregate) == before | {field: new_value}


def test_message_nested_payload_cannot_change_aggregate_state() -> None:
    message = ChatMessage.restore(**AGGREGATE_CASES[ChatMessage].restore_values)
    before = aggregate_state(message)
    message.content.payload["text"] = "modified"
    message.content.to_primitive()["payload"]["text"] = "modified"
    message.conversation_scope.to_primitive()["platform"] = "LINE"

    with pytest.raises(FrozenInstanceError):
        message._content = MessageContent.text("modified")  # pyright: ignore[reportAttributeAccessIssue]
    assert aggregate_state(message) == before
