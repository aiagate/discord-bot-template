"""Tests that entry points load the shared environment configuration."""

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from app import environment
from app.presentation.bot import __main__ as bot_main
from app.presentation.worker import __main__ as worker_main

_FAKE_KEY = "ENTRYPOINT_FAKE_VALUE"
_LINE_MAIN_MODULE = "app.presentation.line.__main__"
_LINE_PACKAGE_MODULE = "app.presentation.line"
_ABSENT: object = object()


def _write_fake_env_local(root: Path, content: str) -> None:
    (root / ".env.local").write_text(content, encoding="utf-8")


def _line_entrypoint_state() -> tuple[object, object, object]:
    """Snapshot the LINE entry-point module cache and package attribute."""
    package = sys.modules.get(_LINE_PACKAGE_MODULE)
    attribute: object = (
        _ABSENT if package is None else package.__dict__.get("__main__", _ABSENT)
    )
    return (sys.modules.get(_LINE_MAIN_MODULE), package, attribute)


def _changed_line_entrypoint_state(before: tuple[object, object, object]) -> list[str]:
    """Return labels for parent-process import state that changed since ``before``."""
    module_before, package_before, attribute_before = before
    module_after, package_after, attribute_after = _line_entrypoint_state()
    changed = []
    if module_after is not module_before:
        changed.append(f"sys.modules[{_LINE_MAIN_MODULE!r}]")
    if package_after is not package_before:
        changed.append(f"sys.modules[{_LINE_PACKAGE_MODULE!r}]")
    if attribute_after is not attribute_before:
        changed.append(f"{_LINE_PACKAGE_MODULE}.__main__ attribute")
    return changed


_LINE_IMPORT_PROBE = """
import json
import sys
from pathlib import Path

from app import environment

environment.resolve_project_root = lambda: Path(sys.argv[1])

import app.presentation.line.__main__ as line_main

print(json.dumps([line_main.channel_secret, line_main.channel_access_token]))
"""


def _import_line_entrypoint(root: Path) -> tuple[str | None, str | None]:
    """Import the LINE entry point in an isolated child process.

    Args:
        root: Directory whose ``.env.local`` the child process loads.

    Returns:
        The channel secret and access token observed by the child process.
    """
    completed = subprocess.run(
        [sys.executable, "-c", _LINE_IMPORT_PROBE, str(root)],
        capture_output=True,
        text=True,
        check=False,
        timeout=60,
        env={"PATH": os.environ.get("PATH", "")},
    )
    assert completed.returncode == 0, completed.stderr
    output_lines = completed.stdout.splitlines()
    assert output_lines, completed.stderr
    credentials: object = json.loads(output_lines[-1])
    assert isinstance(credentials, list) and len(credentials) == 2, completed.stdout
    channel_secret, channel_access_token = credentials
    return channel_secret, channel_access_token


def test_bot_entrypoint_delegates_to_shared_environment_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_environment: None,
) -> None:
    """The Bot entry point loads env files through app.environment."""
    monkeypatch.setattr(environment, "resolve_project_root", lambda: tmp_path)
    _write_fake_env_local(tmp_path, f"{_FAKE_KEY}=from-local\n")

    bot_main.load_environment()

    assert os.environ[_FAKE_KEY] == "from-local"


def test_worker_entrypoint_delegates_to_shared_environment_loader(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    isolated_environment: None,
) -> None:
    """The Worker entry point loads env files through app.environment."""
    monkeypatch.setattr(environment, "resolve_project_root", lambda: tmp_path)
    _write_fake_env_local(tmp_path, f"{_FAKE_KEY}=from-local\n")

    worker_main.load_environment()

    assert os.environ[_FAKE_KEY] == "from-local"


def test_line_entrypoint_loads_credentials_via_shared_loader_at_import(
    tmp_path: Path,
    isolated_environment: None,
) -> None:
    """The LINE entry point keeps import-time credentials via the shared loader."""
    _write_fake_env_local(
        tmp_path,
        "LINE_CHANNEL_SECRET=fake-secret\nLINE_CHANNEL_ACCESS_TOKEN=fake-token\n",
    )
    state_before = _line_entrypoint_state()

    channel_secret, channel_access_token = _import_line_entrypoint(tmp_path)

    assert channel_secret == "fake-secret"
    assert channel_access_token == "fake-token"
    assert _changed_line_entrypoint_state(state_before) == []
