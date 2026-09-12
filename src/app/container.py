"""Dependency injection container configuration."""

import os
from pathlib import Path

import injector
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.application.mediator import (
    ApplicationMediator,
    create_application_mediator,
)
from app.contracts.ports import (
    ICharacterMemoryStore,
    IChatHistoryQuery,
    IUnitOfWork,
    IUserIdentityQuery,
    IUserMemorySourceStore,
    IUserMemoryStore,
)
from app.infrastructure.memory import (
    MarkdownCharacterMemoryStore,
    MarkdownUserMemoryStore,
)
from app.infrastructure.memory.character_memory_store import (
    DEFAULT_CHARACTER_MEMORY_ROOT,
)
from app.infrastructure.memory.user_memory_store import DEFAULT_USER_MEMORY_ROOT
from app.infrastructure.orm_registry import init_orm_mappings
from app.infrastructure.queries.chat_history_query import SQLAlchemyChatHistoryQuery
from app.infrastructure.queries.user_identity_query import SQLAlchemyUserIdentityQuery
from app.infrastructure.queries.user_memory_source_store import (
    SQLAlchemyUserMemorySourceStore,
)
from app.infrastructure.unit_of_work import SQLAlchemyUnitOfWork


class DatabaseModule(injector.Module):
    """Module for database-related dependencies."""

    @injector.provider
    def provide_session_factory(self) -> async_sessionmaker[AsyncSession]:
        """Provide session factory for creating database sessions."""
        from app.infrastructure import database

        if database._session_factory is None:
            raise RuntimeError("Database not initialized. Call init_db() first.")
        return database._session_factory

    @injector.provider
    def provide_unit_of_work(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> IUnitOfWork:
        """Provide Unit of Work implementation for transaction management."""
        return SQLAlchemyUnitOfWork(session_factory)

    @injector.provider
    def provide_chat_history_query(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> IChatHistoryQuery:
        """Provide an isolated read query with factory-owned sessions."""
        return SQLAlchemyChatHistoryQuery(session_factory)

    @injector.provider
    def provide_user_identity_query(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> IUserIdentityQuery:
        """Provide explicit provider-to-canonical-user resolution."""
        return SQLAlchemyUserIdentityQuery(session_factory)

    @injector.provider
    def provide_user_memory_source_store(
        self,
        session_factory: async_sessionmaker[AsyncSession],
    ) -> IUserMemorySourceStore:
        """Provide raw source selection and processed markers."""
        return SQLAlchemyUserMemorySourceStore(session_factory)

    @injector.provider
    @injector.singleton
    def provide_character_memory_store(self) -> ICharacterMemoryStore:
        """Provide Markdown storage for selected character memories."""
        configured_root = os.getenv("CHARACTER_MEMORY_ROOT", "").strip()
        root = (
            Path(configured_root) if configured_root else DEFAULT_CHARACTER_MEMORY_ROOT
        )
        return MarkdownCharacterMemoryStore(root)

    @injector.provider
    @injector.singleton
    def provide_user_memory_store(self) -> IUserMemoryStore:
        """Provide isolated Markdown storage for canonical-user memory."""
        configured_root = os.getenv("USER_MEMORY_ROOT", "").strip()
        root = Path(configured_root) if configured_root else DEFAULT_USER_MEMORY_ROOT
        return MarkdownUserMemoryStore(root)


class ApplicationModule(injector.Module):
    """Module for application-level orchestration services."""

    @injector.provider
    @injector.singleton
    def provide_mediator(self, container: injector.Injector) -> ApplicationMediator:
        """Provide the mediator with all application handlers registered."""
        return create_application_mediator(container)


def configure(binder: injector.Binder) -> None:
    """Configure dependency injection bindings."""
    # Initialize ORM mappings
    init_orm_mappings()

    binder.install(DatabaseModule())
    binder.install(ApplicationModule())
