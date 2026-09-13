"""Fixtures for provider-independent acceptance scenarios."""

from pathlib import Path

import pytest

from app.infrastructure.store import LocalStore


@pytest.fixture
def anyio_backend() -> str:
    """Run anyio tests on the runtime's asyncio backend."""
    return "asyncio"


@pytest.fixture
def store(tmp_path: Path) -> LocalStore:
    """Create an isolated, initialized collective without external credentials."""
    result = LocalStore(tmp_path / "collective")
    result.initialize()
    (result.root / "master.md").write_text(
        "選び直せる形で、自分で必要な一手を判断する。"
    )
    return result
