"""Tests for database JSON serialization configuration."""

from typing import Any, cast

from sqlalchemy.ext.asyncio import create_async_engine

from app.infrastructure.database import init_db


def _custom_serializer(obj: Any) -> str:
    """Return a stable JSON placeholder for override testing."""

    return "{}"


def test_init_db_disables_ascii_escaping_for_json() -> None:
    """SQLite JSON serialization should preserve non-ASCII text."""

    from app.infrastructure import database

    old_engine = database._engine
    old_session_factory = database._session_factory
    init_db("sqlite+aiosqlite:///:memory:")

    try:
        assert database._engine is not None
        serializer = cast(Any, database._engine.sync_engine.dialect)._json_serializer
        assert serializer is not None
        assert serializer({"text": "こんにちは"}) == '{"text": "こんにちは"}'
    finally:
        database._engine = old_engine
        database._session_factory = old_session_factory


def test_sqlite_json_serializer_can_be_overridden() -> None:
    """Explicit serializer overrides should still be respected."""

    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        json_serializer=_custom_serializer,
    )

    dialect = cast(Any, engine.sync_engine.dialect)
    assert dialect._json_serializer is not None
    assert dialect._json_serializer({"text": "こんにちは"}) == "{}"
