"""Tests for the shared project environment loader."""

import os
from pathlib import Path

import pytest

from app.environment import load_environment, resolve_project_root

_FAKE_KEY = "ENVLOADER_TEST_KEY"
_FAKE_BASE_ONLY_KEY = "ENVLOADER_TEST_BASE_ONLY_KEY"


def test_resolve_project_root_is_stable_regardless_of_cwd(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The project root is resolved from this module, not from the CWD."""
    monkeypatch.chdir(tmp_path)

    root = resolve_project_root()

    assert (root / "pyproject.toml").is_file()
    assert (root / "src" / "app" / "environment.py").is_file()


def test_env_local_overrides_base_env(
    tmp_path: Path, isolated_environment: None
) -> None:
    """Values in .env.local win over the same keys in .env."""
    (tmp_path / ".env").write_text(
        f"{_FAKE_KEY}=base\n{_FAKE_BASE_ONLY_KEY}=base-only\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text(f"{_FAKE_KEY}=local\n", encoding="utf-8")

    load_environment(tmp_path)

    assert os.environ[_FAKE_KEY] == "local"
    assert os.environ[_FAKE_BASE_ONLY_KEY] == "base-only"


def test_base_env_is_loaded_when_local_is_missing(
    tmp_path: Path, isolated_environment: None
) -> None:
    """.env acts as the fallback when .env.local does not exist."""
    (tmp_path / ".env").write_text(f"{_FAKE_KEY}=base\n", encoding="utf-8")

    load_environment(tmp_path)

    assert os.environ[_FAKE_KEY] == "base"


def test_process_environment_is_never_overridden(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_environment: None
) -> None:
    """Externally provided variables take precedence over both files."""
    monkeypatch.setenv(_FAKE_KEY, "process")
    (tmp_path / ".env").write_text(f"{_FAKE_KEY}=base\n", encoding="utf-8")
    (tmp_path / ".env.local").write_text(f"{_FAKE_KEY}=local\n", encoding="utf-8")

    load_environment(tmp_path)

    assert os.environ[_FAKE_KEY] == "process"


def test_missing_env_files_are_tolerated(
    tmp_path: Path, isolated_environment: None
) -> None:
    """A root without any env files is a valid no-op."""
    before = dict(os.environ)

    load_environment(tmp_path)

    assert dict(os.environ) == before


def test_loading_is_independent_of_current_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, isolated_environment: None
) -> None:
    """Env files are read from the explicit root, never from the CWD."""
    (tmp_path / ".env").write_text(f"{_FAKE_KEY}=explicit-root\n", encoding="utf-8")
    elsewhere = tmp_path / "somewhere-else"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    (elsewhere / ".env").write_text(f"{_FAKE_KEY}=cwd\n", encoding="utf-8")

    load_environment(tmp_path)

    assert os.environ[_FAKE_KEY] == "explicit-root"
