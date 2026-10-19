"""Tests that the Alembic environment loads project env files."""

import runpy
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest
from alembic.config import Config

import alembic
from app import environment


def test_alembic_env_loads_environment_before_reading_database_url(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_environment: None,
) -> None:
    """DATABASE_URL reaches alembic from .env.local, overriding .env."""
    local_db = tmp_path / "local.db"
    (tmp_path / ".env").write_text(
        "DATABASE_URL=sqlite+aiosqlite:///./base.db\n",
        encoding="utf-8",
    )
    (tmp_path / ".env.local").write_text(
        f"DATABASE_URL=sqlite+aiosqlite:///{local_db}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(environment, "resolve_project_root", lambda: tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)

    config = Config()

    class _FakeContext:
        def __init__(self, alembic_config: Config) -> None:
            self.config = alembic_config

        def is_offline_mode(self) -> bool:
            return True

        def configure(self, **kwargs: Any) -> None:
            self.configure_kwargs = kwargs

        @contextmanager
        def begin_transaction(self) -> Any:
            yield

        def run_migrations(self) -> None:
            return None

    monkeypatch.setattr(alembic, "context", _FakeContext(config))

    runpy.run_path(
        str(_repo_root() / "alembic" / "env.py"),
        run_name="__alembic_env_test__",
    )

    assert config.get_main_option("sqlalchemy.url") == (
        f"sqlite+aiosqlite:///{local_db}"
    )


def _repo_root() -> Path:
    """Return the real repository root before test monkeypatching."""
    return Path(__file__).resolve().parents[1]
