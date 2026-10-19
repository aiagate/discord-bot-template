"""Tests for the API entry point lifespan startup."""

from pathlib import Path

import pytest

from app import environment
from app.presentation.api import __main__ as api_main


@pytest.mark.anyio
async def test_lifespan_loads_environment_before_init_db(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_environment: None,
) -> None:
    """init_db receives the DATABASE_URL resolved from .env.local."""
    scratch_db = tmp_path / "api.db"
    (tmp_path / ".env.local").write_text(
        f"DATABASE_URL=sqlite+aiosqlite:///{scratch_db}\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(environment, "resolve_project_root", lambda: tmp_path)
    monkeypatch.delenv("DATABASE_URL", raising=False)
    recorded_urls: list[str] = []

    def fake_init_db(db_url: str, echo: bool = False) -> None:
        recorded_urls.append(db_url)

    monkeypatch.setattr(api_main, "init_db", fake_init_db)

    async with api_main.lifespan(api_main.app):
        assert recorded_urls == [f"sqlite+aiosqlite:///{scratch_db}"]
