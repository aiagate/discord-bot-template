"""Tests for DisplayName value object."""

from flow_res import Err, Ok

from app.domain.value_objects.display_name import DisplayName


def test_display_name_from_primitive_with_valid_name() -> None:
    """Test creating DisplayName from valid string."""
    result = DisplayName.from_primitive("John Doe")
    assert isinstance(result, Ok)
    display_name = result.expect(
        "DisplayName.from_primitive should succeed for valid name"
    )
    assert display_name.to_primitive() == "John Doe"


def test_display_name_from_primitive_with_empty_string() -> None:
    """Test that empty string returns Err."""
    result = DisplayName.from_primitive("")
    assert isinstance(result, Err)
    assert "Display name cannot be empty" in str(result.error)


def test_display_name_from_primitive_with_whitespace() -> None:
    """Test that whitespace-only string returns Err."""
    result = DisplayName.from_primitive("   ")
    assert isinstance(result, Err)
    # Detected as having leading/trailing whitespace before empty check
    assert "leading or trailing whitespace" in str(result.error)


def test_display_name_from_primitive_with_leading_whitespace() -> None:
    """Test that string with leading whitespace returns Err."""
    result = DisplayName.from_primitive("  John")
    assert isinstance(result, Err)
    assert "leading or trailing whitespace" in str(result.error)


def test_display_name_from_primitive_with_trailing_whitespace() -> None:
    """Test that string with trailing whitespace returns Err."""
    result = DisplayName.from_primitive("John  ")
    assert isinstance(result, Err)
    assert "leading or trailing whitespace" in str(result.error)


def test_display_name_from_primitive_exceeds_max_length() -> None:
    """Test that string exceeding max length returns Err."""
    long_name = "a" * (DisplayName.MAX_LENGTH + 1)
    result = DisplayName.from_primitive(long_name)
    assert isinstance(result, Err)
    assert "must not exceed" in str(result.error)


def test_display_name_str_representation() -> None:
    """Test __str__ returns the primitive value."""
    display_name = DisplayName.from_primitive("Alice").expect(
        "DisplayName.from_primitive should succeed for valid name"
    )
    assert str(display_name) == "Alice"


def test_display_name_repr() -> None:
    """Test __repr__ returns developer-friendly representation."""
    display_name = DisplayName.from_primitive("Alice").expect(
        "DisplayName.from_primitive should succeed for valid name"
    )
    assert repr(display_name) == "DisplayName(Alice)"


def test_display_name_equality() -> None:
    """Test that two DisplayName instances with same value are equal."""
    name1 = DisplayName.from_primitive("Bob").expect(
        "DisplayName.from_primitive should succeed for valid name"
    )
    name2 = DisplayName.from_primitive("Bob").expect(
        "DisplayName.from_primitive should succeed for valid name"
    )
    assert name1 == name2


def test_display_name_immutability() -> None:
    """Test that DisplayName is immutable (frozen dataclass)."""
    import dataclasses

    import pytest

    display_name = DisplayName.from_primitive("Charlie").expect(
        "DisplayName.from_primitive should succeed for valid name"
    )
    with pytest.raises(dataclasses.FrozenInstanceError):
        display_name._value = "NewName"  # type: ignore[misc]
