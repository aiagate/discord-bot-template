"""Forward and backward compatibility of delivery tracking migrations."""

import importlib.util
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine


def _migration() -> Any:
    path = (
        Path(__file__).parents[2]
        / "alembic/versions/202609120900_6f12b7d83e40_add_character_delivery_tracking.py"
    )
    spec = importlib.util.spec_from_file_location("speech_delivery_migration", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_upgrade_and_downgrade_preserve_existing_chat_rows() -> None:
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    migration = _migration()
    try:
        async with engine.begin() as connection:
            await connection.execute(
                sa.text(
                    "CREATE TABLE chat_messages (id TEXT PRIMARY KEY, platform TEXT NOT NULL, content TEXT NOT NULL)"
                )
            )
            await connection.execute(
                sa.text(
                    "INSERT INTO chat_messages VALUES ('old1', 'DISCORD', 'one'), ('old2', 'DISCORD', 'two')"
                )
            )

            def upgrade(sync: sa.Connection) -> None:
                with Operations.context(MigrationContext.configure(sync)):
                    migration.upgrade()

            await connection.run_sync(upgrade)
            assert (
                await connection.execute(
                    sa.text("SELECT external_message_id FROM chat_messages")
                )
            ).scalars().all() == [None, None]
            await connection.execute(
                sa.text(
                    "UPDATE chat_messages SET external_message_id='900' WHERE id='old1'"
                )
            )
            with pytest.raises(IntegrityError):
                await connection.execute(
                    sa.text(
                        "UPDATE chat_messages SET external_message_id='900' WHERE id='old2'"
                    )
                )

            def downgrade(sync: sa.Connection) -> None:
                with Operations.context(MigrationContext.configure(sync)):
                    migration.downgrade()
                assert "speech_deliveries" not in sa.inspect(sync).get_table_names()
                assert {
                    column["name"]
                    for column in sa.inspect(sync).get_columns("chat_messages")
                } == {"id", "platform", "content"}

            await connection.run_sync(downgrade)
            assert (
                await connection.execute(
                    sa.text("SELECT id, content FROM chat_messages ORDER BY id")
                )
            ).all() == [("old1", "one"), ("old2", "two")]
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
    assert "CREATE TABLE speech_deliveries" in ddl
    assert "CREATE UNIQUE INDEX uq_chat_messages_external_id" in ddl
    assert "reply_to_external_message_id" in ddl
