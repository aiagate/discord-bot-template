"""Discover application definitions in tests to catch missing explicit registration."""

import inspect
import subprocess
import sys
from importlib import import_module
from pathlib import Path
from pkgutil import walk_packages
from types import ModuleType

import pytest
from flow_med import RequestHandler
from sqlalchemy import inspect as inspect_orm

from app import usecases
from app.application.mediator import _HANDLER_TYPES
from app.domain import aggregates
from app.infrastructure.orm_mapping import ORMMappingRegistry
from app.infrastructure.orm_registry import init_orm_mappings
from tests.domain.aggregate_cases import VERSION_EXEMPTIONS

NON_PERSISTED_AGGREGATES: dict[type, str] = {}


def _defined_classes(package: ModuleType) -> set[type]:
    discovered: set[type] = set()
    for module_info in walk_packages(package.__path__, package.__name__ + "."):
        module = import_module(module_info.name)
        discovered.update(
            value
            for value in vars(module).values()
            if inspect.isclass(value) and value.__module__ == module.__name__
        )
    return discovered


def test_defined_aggregates_are_public_and_registered() -> None:
    defined = {
        aggregate
        for aggregate in _defined_classes(aggregates)
        if not issubclass(aggregate, Exception) and not inspect.isabstract(aggregate)
    }
    public = {getattr(aggregates, name) for name in aggregates.__all__}
    assert defined == public
    assert all(NON_PERSISTED_AGGREGATES.values())
    assert set(NON_PERSISTED_AGGREGATES) <= public
    init_orm_mappings()
    assert public - set(NON_PERSISTED_AGGREGATES) <= set(
        ORMMappingRegistry.get_mapping_dict()
    )


def test_defined_handlers_are_registered_exactly_once() -> None:
    defined = {
        handler
        for handler in _defined_classes(usecases)
        if issubclass(handler, RequestHandler) and not inspect.isabstract(handler)
    }
    assert defined == set(_HANDLER_TYPES)
    assert len(_HANDLER_TYPES) == len(set(_HANDLER_TYPES))


def test_application_mapping_initialization_is_idempotent() -> None:
    init_orm_mappings()
    before = ORMMappingRegistry.get_mapping_dict()
    init_orm_mappings()
    assert ORMMappingRegistry.get_mapping_dict() == before


def test_mutable_aggregate_mappers_use_the_version_column() -> None:
    assert all(VERSION_EXEMPTIONS.values())
    assert set(VERSION_EXEMPTIONS) <= {
        getattr(aggregates, name) for name in aggregates.__all__
    }
    for name in aggregates.__all__:
        aggregate_type = getattr(aggregates, name)
        if aggregate_type in NON_PERSISTED_AGGREGATES:
            continue
        orm_type = ORMMappingRegistry.get_orm_type(aggregate_type)
        assert orm_type is not None
        mapper = inspect_orm(orm_type)
        assert mapper is not None
        if aggregate_type in VERSION_EXEMPTIONS:
            assert not hasattr(aggregate_type, "version")
            assert mapper.version_id_col is None
        else:
            assert mapper.version_id_col is mapper.columns.version
            assert mapper.version_id_generator is False


@pytest.mark.parametrize("entrypoint", ["models", "application", "alembic"])
def test_cold_start_loads_all_application_tables(entrypoint: str) -> None:
    setup = {
        "models": "from app.infrastructure import orm_models",
        "application": "from injector import Injector\nfrom app.container import configure\nInjector([configure])",
        "alembic": """
from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.runtime.environment import EnvironmentContext
config = Config('alembic.ini')
script = ScriptDirectory.from_config(config)
with EnvironmentContext(config, script, as_sql=True, fn=lambda *_: []):
    script.run_env()
""",
    }[entrypoint]
    verification = """
loaded_tables = set(SQLModel.metadata.tables)
from importlib import import_module
from pkgutil import walk_packages
from app.infrastructure import orm_models
from sqlalchemy import inspect
models = set()
for info in walk_packages(orm_models.__path__, orm_models.__name__ + '.'):
    module = import_module(info.name)
    for value in vars(module).values():
        if isinstance(value, type) and value.__module__ == module.__name__:
            mapper = inspect(value, raiseerr=False)
            if mapper is not None:
                models.add(value)
public_models = {getattr(orm_models, name) for name in orm_models.__all__}
assert public_models == models, (public_models, models)
expected_tables = {inspect(model).local_table.key for model in models}
assert loaded_tables == expected_tables, (loaded_tables, expected_tables)
"""
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            "from sqlmodel import SQLModel\n" + setup + "\n" + verification,
        ],
        cwd=Path(__file__).resolve().parents[2],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
