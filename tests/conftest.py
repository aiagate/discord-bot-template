"""Pytest configuration and fixtures."""

import os
from collections.abc import AsyncGenerator
from pathlib import Path
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest
from sqlalchemy import event
from sqlalchemy.engine import make_url
from sqlalchemy.engine.interfaces import DBAPIConnection
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.schema import CreateSchema, DropSchema
from sqlmodel import SQLModel

from app.contracts.ports import IChatHistoryQuery, IEventBus, IUnitOfWork
from app.infrastructure.orm_registry import init_orm_mappings
from app.infrastructure.queries.chat_history_query import SQLAlchemyChatHistoryQuery
from app.infrastructure.unit_of_work import SQLAlchemyUnitOfWork

# Initialize ORM mappings before any tests
init_orm_mappings()


@pytest.fixture(scope="function")
async def database_engine(tmp_path: Path) -> AsyncGenerator[AsyncEngine]:
    """Isolate each test in a temporary SQLite file or PostgreSQL schema."""
    test_url = make_url(os.environ.get("TEST_DATABASE_URL", "sqlite+aiosqlite://"))
    if test_url.drivername not in {"sqlite+aiosqlite", "postgresql+asyncpg"}:
        pytest.fail("TEST_DATABASE_URL must use sqlite+aiosqlite or postgresql+asyncpg")
    if test_url.drivername == "sqlite+aiosqlite" and test_url.database not in {
        None,
        "",
        ":memory:",
    }:
        pytest.fail("Use sqlite+aiosqlite:// to request an isolated temporary database")

    engine: AsyncEngine | None = None
    control_engine: AsyncEngine | None = None
    schema = f"test_{uuid4().hex}"
    schema_created = False

    try:
        if test_url.drivername == "postgresql+asyncpg":
            control_engine = create_async_engine(test_url)
            async with control_engine.begin() as connection:
                await connection.execute(CreateSchema(schema))
            schema_created = True
            engine = create_async_engine(
                test_url,
                connect_args={"server_settings": {"search_path": schema}},
            )
        else:
            engine = create_async_engine(
                test_url.set(database=str(tmp_path / "test.db")),
                connect_args={"timeout": 10},
            )

            def enable_foreign_keys(
                connection: DBAPIConnection, _connection_record: object
            ) -> None:
                cursor = connection.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

            event.listen(engine.sync_engine, "connect", enable_foreign_keys)

        async with engine.begin() as connection:
            await connection.run_sync(SQLModel.metadata.create_all)
        yield engine
    finally:
        if engine is not None:
            await engine.dispose()
        if control_engine is not None:
            try:
                if schema_created:
                    async with control_engine.begin() as connection:
                        await connection.execute(DropSchema(schema, cascade=True))
            finally:
                await control_engine.dispose()


@pytest.fixture(scope="function")
async def test_db_engine(database_engine: AsyncEngine) -> AsyncGenerator[None]:
    """Temporarily bind application database access to the isolated test engine."""

    from app.infrastructure import database

    old_engine = database._engine
    old_session_factory = database._session_factory

    database._engine = database_engine
    database._session_factory = async_sessionmaker(
        database_engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    try:
        yield
    finally:
        database._engine = old_engine
        database._session_factory = old_session_factory


@pytest.fixture(scope="function")
async def session_factory(
    test_db_engine: None,
) -> async_sessionmaker[AsyncSession]:
    """Provide session factory for tests."""
    from app.infrastructure import database

    if database._session_factory is None:
        raise RuntimeError("Database not initialized")
    return database._session_factory


@pytest.fixture(scope="function")
def anyio_backend() -> str:
    """Specify anyio backend for pytest-anyio."""
    return "asyncio"


@pytest.fixture
def event_bus() -> AsyncMock:
    """Provide a mock event bus for tests."""
    return AsyncMock(spec=IEventBus)


@pytest.fixture
async def uow(
    session_factory: async_sessionmaker[AsyncSession],
) -> IUnitOfWork:
    """Provide Unit of Work for tests."""
    return SQLAlchemyUnitOfWork(session_factory)


@pytest.fixture
def chat_history_query(
    session_factory: async_sessionmaker[AsyncSession],
) -> IChatHistoryQuery:
    """Provide a query port with an independent session per call."""
    return SQLAlchemyChatHistoryQuery(session_factory)
