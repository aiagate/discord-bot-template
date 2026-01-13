"""Alembic environment configuration for async SQLModel migrations."""

import asyncio
import os
from logging.config import fileConfig

from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlmodel import SQLModel

from alembic import context

# Import all ORM models here for autogenerate to discover them
from app.infrastructure.orm_models import (
    ChatMessageORM,  # pyright: ignore[reportUnusedImport] # noqa: F401
    SystemInstructionORM,  # pyright: ignore[reportUnusedImport] # noqa: F401
    TeamMembershipORM,  # pyright: ignore[reportUnusedImport] # noqa: F401
    TeamORM,  # pyright: ignore[reportUnusedImport] # noqa: F401
    UserORM,  # pyright: ignore[reportUnusedImport] # noqa: F401
)

# this is the Alembic Config object
config = context.config

# Override sqlalchemy.url with environment variable if available
database_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./bot.db")
config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Set target metadata for autogenerate
target_metadata = SQLModel.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=bool(url and "sqlite" in url),
    )

    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection: Connection) -> None:
    """Run migrations with given connection."""
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        render_as_batch=connection.dialect.name.startswith("sqlite"),
    )

    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """Run migrations in async mode."""
    configuration = config.get_section(config.config_ini_section, {})
    connectable = async_engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    asyncio.run(run_async_migrations())


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
