"""Tests for character-owned memory validation."""

from datetime import UTC, datetime

import pytest

from app.domain.character_memory import CharacterMemory


def _memory(**overrides: object) -> CharacterMemory:
    """Build one valid memory fixture."""
    values: dict[str, object] = {
        "character_id": "Dorothy",
        "source_message_id": "source-1",
        "sequence": 0,
        "content": "ユーザーは朝に作業する。",
        "observed_at": datetime(2026, 9, 12, tzinfo=UTC),
    }
    values.update(overrides)
    return CharacterMemory(**values)  # type: ignore[arg-type]


def test_memory_normalizes_text_and_timestamp() -> None:
    memory = _memory(
        character_id=" Dorothy ",
        content=" ユーザーは朝に作業する。 ",
        observed_at=datetime(2026, 9, 12, tzinfo=UTC),
    )

    assert memory.character_id == "Dorothy"
    assert memory.content == "ユーザーは朝に作業する。"


@pytest.mark.parametrize(
    "field,value",
    [
        ("character_id", " "),
        ("source_message_id", " "),
        ("content", " "),
        ("sequence", -1),
        ("observed_at", datetime(2026, 9, 12)),
    ],
)
def test_memory_rejects_invalid_values(field: str, value: object) -> None:
    with pytest.raises(ValueError):
        _memory(**{field: value})


def test_memory_rejects_long_content() -> None:
    with pytest.raises(ValueError, match="maximum length"):
        _memory(content="x" * 501)
