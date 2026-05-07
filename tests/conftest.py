"""Pytest configuration and fixtures."""

from collections.abc import AsyncGenerator
from unittest.mock import AsyncMock

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import SQLModel

from app.domain.interfaces.event_bus import IEventBus
from app.domain.repositories import IUnitOfWork
from app.infrastructure.orm_registry import init_orm_mappings
from app.infrastructure.unit_of_work import SQLAlchemyUnitOfWork

# Initialize ORM mappings before any tests
init_orm_mappings()


@pytest.fixture(scope="function")
async def test_db_engine() -> AsyncGenerator[None]:
    """Create test database engine with in-memory SQLite."""
    test_url = "sqlite+aiosqlite:///:memory:"

    engine = create_async_engine(test_url, echo=False)

    async with engine.begin() as conn:
        await conn.run_sync(SQLModel.metadata.create_all)

    from app.infrastructure import database

    old_engine = database._engine
    old_session_factory = database._session_factory

    database._engine = engine
    database._session_factory = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )

    yield

    database._engine = old_engine
    database._session_factory = old_session_factory
    await engine.dispose()


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
