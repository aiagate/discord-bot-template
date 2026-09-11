"""Boundary tests for Discord's character limit and readable splitting."""

import re

import pytest

from app.infrastructure.discord.message_chunks import split_discord_content


@pytest.mark.parametrize("content", ["", "  \n\t"])
def test_empty_text_produces_no_parts(content: str) -> None:
    assert split_discord_content(content) == ()


@pytest.mark.parametrize("separator", ["\n\n", "\n", "。", ". ", " "])
def test_prefers_readable_boundaries(separator: str) -> None:
    first, second = "あ" * 36, "い" * 40
    parts = split_discord_content(first + separator + second, limit=64)
    assert parts == ((first + separator).rstrip(), second)


@pytest.mark.parametrize("content", ["あ" * 8001, "😀" * 4001, "abc\n\n" * 2000])
def test_long_lines_and_unicode_fit_without_losing_text(content: str) -> None:
    parts = split_discord_content(content)
    assert len(parts) > 1
    assert all(0 < len(part.encode("utf-16-le")) // 2 <= 2000 for part in parts)
    assert re.sub(r"\s", "", "".join(parts)) == re.sub(r"\s", "", content)


def test_fenced_code_is_closed_and_reopened_between_parts() -> None:
    content = "```python\n" + "print('hello')\n" * 80 + "```"
    parts = split_discord_content(content, limit=128)
    assert len(parts) > 1
    assert all(
        part.startswith("```python\n") and part.endswith("```") for part in parts
    )
    assert sum(part.count("print('hello')") for part in parts) == 80
    assert all(len(part) <= 128 for part in parts)


def test_unusually_long_fence_label_still_makes_progress() -> None:
    parts = split_discord_content(
        "```" + "語" * 1000 + "\n" + "x" * 400 + "\n```", limit=64
    )
    assert parts
    assert all(0 < len(part.encode("utf-16-le")) // 2 <= 64 for part in parts)


def test_limit_must_leave_room_for_fences() -> None:
    with pytest.raises(ValueError):
        split_discord_content("x", limit=10)
