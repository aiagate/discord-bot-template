from flow_res import Err

"""Tests for domain models."""

from datetime import UTC, datetime

from app.domain.aggregates.user import User
from app.domain.value_objects import DisplayName, Email


def test_create_user_with_empty_name_raises_error() -> None:
    """Test that creating a User with an empty display name returns Err."""
    result = DisplayName.from_primitive("")
    assert isinstance(result, Err)
    assert "Display name cannot be empty" in str(result.error)


def test_user_change_email() -> None:
    """Test that the change_email method updates the user's email."""
    user = User.register(
        display_name=DisplayName.from_primitive("Test User").expect(
            "DisplayName.from_primitive should succeed for valid display name"
        ),
        email=Email.from_primitive("old@example.com").expect(
            "Email.from_primitive should succeed for valid email"
        ),
    )
    user.change_email(
        Email.from_primitive("new@example.com").expect(
            "Email.from_primitive should succeed for valid email"
        )
    )
    assert user.email.to_primitive() == "new@example.com"


def test_user_creation_with_valid_data() -> None:
    """Test creating a user with valid data."""
    email = Email.from_primitive("alice@example.com").expect(
        "Email.from_primitive should succeed for valid email"
    )
    display_name = DisplayName.from_primitive("Alice").expect(
        "DisplayName.from_primitive should succeed for valid display name"
    )
    user = User.register(display_name=display_name, email=email)
    assert user.display_name == display_name
    assert user.email == email
    assert isinstance(user.created_at, datetime)
    assert isinstance(user.updated_at, datetime)


def test_user_timestamps_use_utc() -> None:
    """Test that user timestamps use UTC timezone."""
    before = datetime.now(UTC)
    user = User.register(
        display_name=DisplayName.from_primitive("Test").expect(
            "DisplayName.from_primitive should succeed for valid display name"
        ),
        email=Email.from_primitive("test@example.com").expect(
            "Email.from_primitive should succeed for valid email"
        ),
    )
    after = datetime.now(UTC)

    assert before <= user.created_at <= after
    assert before <= user.updated_at <= after


def test_creation_with_invalid_email_returns_err() -> None:
    """Test that creating user with invalid email raises ValueError."""
    result = Email.from_primitive("invalid-email")
    assert isinstance(result, Err)
    assert "Invalid email format" in str(result.error)
