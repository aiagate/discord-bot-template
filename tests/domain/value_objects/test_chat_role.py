"""Tests for ChatRole value object."""

from app.core.result import is_err, is_ok
from app.domain.value_objects.chat_role import ChatRole


def test_chat_role_create_success() -> None:
    """Test creating ChatRole from valid strings."""
    # Test lowercase
    res1 = ChatRole.from_primitive("user")
    assert is_ok(res1)
    assert res1.value == ChatRole.USER

    res2 = ChatRole.from_primitive("model")
    assert is_ok(res2)
    assert res2.value == ChatRole.MODEL

    # Test mixed case (should be handled if logic permits, or fail.
    # Looking at implementation: return Ok(cls(value.lower()))
    # So mixed case should work.
    res3 = ChatRole.from_primitive("USER")
    assert is_ok(res3)
    assert res3.value == ChatRole.USER

    res4 = ChatRole.from_primitive("Model")
    assert is_ok(res4)
    assert res4.value == ChatRole.MODEL


def test_chat_role_create_failure() -> None:
    """Test creating ChatRole from invalid strings."""
    res = ChatRole.from_primitive("invalid_role")
    assert is_err(res)
    assert isinstance(res.error, ValueError)
    assert str(res.error) == "Invalid chat role: invalid_role"
