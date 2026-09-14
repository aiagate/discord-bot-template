"""Tests for the private master personalization context loader."""

from pathlib import Path

import pytest

from app.application.master_context import (
    MAX_MASTER_CONTEXT_LENGTH,
    load_master_context,
)


def test_load_master_context_reads_utf8_and_trims_whitespace(tmp_path: Path) -> None:
    path = tmp_path / "master_context.md"
    path.write_text("\n  好みの情報です。  \n", encoding="utf-8")

    assert load_master_context(path) == "好みの情報です。"


def test_load_master_context_treats_an_empty_file_as_unconfigured(
    tmp_path: Path,
) -> None:
    path = tmp_path / "master_context.md"
    path.write_text(" \n", encoding="utf-8")

    assert load_master_context(path) is None
    assert load_master_context(None) is None


@pytest.mark.parametrize("path_kind", ["missing", "directory"])
def test_load_master_context_rejects_invalid_path(
    tmp_path: Path, path_kind: str
) -> None:
    path = tmp_path / "master_context.md"
    if path_kind == "directory":
        path.mkdir()

    with pytest.raises(ValueError):
        load_master_context(path)


def test_load_master_context_rejects_overlong_file(tmp_path: Path) -> None:
    path = tmp_path / "master_context.md"
    path.write_text("x" * (MAX_MASTER_CONTEXT_LENGTH + 1), encoding="utf-8")

    with pytest.raises(ValueError, match="maximum length"):
        load_master_context(path)
