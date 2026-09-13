"""Tests for Times schema upgrades and rollback."""

import importlib.util
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.ext.asyncio import create_async_engine

from alembic import command


def _migration() -> Any:
    path = (
        Path(__file__).parents[2]
        / "alembic/versions/202609121500_e4a7b8c9d012_add_times_episodes.py"
    )
    spec = importlib.util.spec_from_file_location("times_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_upgrade_and_downgrade_times_episodes_table() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    migration = _migration()
    try:
        async with engine.begin() as connection:

            def upgrade(sync: sa.Connection) -> None:
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()

            await connection.run_sync(upgrade)

            def check_tables(sync: sa.Connection) -> list[str]:
                return sa.inspect(sync).get_table_names()

            tables = await connection.run_sync(check_tables)
            assert "times_episodes" in tables

            def downgrade(sync: sa.Connection) -> None:
                with Operations.context(MigrationContext.configure(sync)):
                    migration.downgrade()

            await connection.run_sync(downgrade)
            tables_after = await connection.run_sync(check_tables)
            assert "times_episodes" not in tables_after
    finally:
        await engine.dispose()


@pytest.mark.parametrize("url", ["sqlite://", "postgresql://"])
def test_migration_generates_portable_offline_sql(url: str) -> None:
    output = StringIO()
    context = MigrationContext.configure(
        url=url, opts={"as_sql": True, "output_buffer": output}
    )
    with Operations.context(context):
        _migration().upgrade()
    ddl = output.getvalue()
    assert "CREATE TABLE times_episodes" in ddl


def test_branch_migrations_preserve_main_data_without_sql_character_memory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upgrade from main and roll back using the real revision chain on a temporary DB."""
    database_path = tmp_path / "migrations.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{database_path}")
    config = Config()
    config.set_main_option(
        "script_location", str(Path(__file__).parents[2] / "alembic")
    )
    main_revision = "7d5f0d6a2b31"
    engine = sa.create_engine(f"sqlite:///{database_path}")
    try:
        command.upgrade(config, main_revision)
        messages = sa.Table("chat_messages", sa.MetaData(), autoload_with=engine)
        with engine.begin() as connection:
            connection.execute(
                messages.insert().values(
                    id="existing-message",
                    platform="DISCORD",
                    conversation_scope={"guild_id": "456", "channel_id": "123"},
                    external_sender_id="2",
                    author_kind="USER",
                    content={"type": "text", "payload": {"text": "existing chat"}},
                    occurred_at=datetime(2026, 9, 12, tzinfo=UTC),
                )
            )

        command.upgrade(config, "head")
        tables = sa.inspect(engine).get_table_names()
        assert {"speech_deliveries", "times_episodes"} <= set(tables)
        assert "character_memories" not in tables
        with engine.connect() as connection:
            assert connection.scalar(sa.select(messages.c.content)) == {
                "type": "text",
                "payload": {"text": "existing chat"},
            }

        command.downgrade(config, main_revision)
        tables = sa.inspect(engine).get_table_names()
        assert "speech_deliveries" not in tables
        assert "times_episodes" not in tables
        with engine.connect() as connection:
            assert connection.scalar(sa.select(messages.c.id)) == "existing-message"
    finally:
        engine.dispose()
