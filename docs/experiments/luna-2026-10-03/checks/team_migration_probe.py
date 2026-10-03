"""Independent migration checks for either held-out Team text attribute."""

import argparse
import json
import os
import sqlite3
import sys
import traceback
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

BASELINE_HEAD = "7d5f0d6a2b31"
RESULTS: list[dict[str, Any]] = []


def check(name: str, passed: bool, detail: Any = None) -> None:
    """Record each result, retaining failures until the final exit."""
    RESULTS.append({"check": name, "passed": bool(passed), "detail": detail})


def rows(path: Path) -> list[dict[str, Any]]:
    """Read all seeded rows, including audit and version fields."""
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return [
            dict(row) for row in connection.execute("SELECT * FROM teams ORDER BY id")
        ]


def run(field: str) -> bool:
    """Upgrade, downgrade and reupgrade both legacy data and a clean database."""
    config = Config("alembic.ini")
    script = ScriptDirectory.from_config(config)
    heads = script.get_heads()
    check("one_new_head", len(heads) == 1 and heads[0] != BASELINE_HEAD, heads)
    with TemporaryDirectory(prefix="luna-migration-acceptance-") as directory:
        legacy = Path(directory) / "legacy.db"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{legacy}"
        command.upgrade(config, BASELINE_HEAD)
        with sqlite3.connect(legacy) as connection:
            connection.executemany(
                "INSERT INTO teams(id, name, version, created_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?)",
                [
                    (
                        "01ARZ3NDEKTSV4RRFFQ69G5FAV",
                        "Legacy",
                        7,
                        "2026-01-01 00:00:00",
                        "2026-02-01 00:00:00",
                    ),
                    (
                        "01ARZ3NDEKTSV4RRFFQ69G5FAW",
                        "既存チーム",
                        0,
                        "2026-02-01 01:02:03",
                        "2026-02-01 01:02:03",
                    ),
                ],
            )
        before = rows(legacy)
        command.upgrade(config, "head")
        after = rows(legacy)
        check(
            "legacy_default_empty",
            len(after) == 2 and all(row.get(field) == "" for row in after),
            after,
        )
        check(
            "legacy_all_columns_preserved",
            len(after) == len(before)
            and all(
                all(new.get(k) == v for k, v in old.items())
                for old, new in zip(before, after, strict=True)
            ),
            after,
        )
        command.check(config)
        check("upgraded_schema_matches", True)
        command.downgrade(config, BASELINE_HEAD)
        check("downgrade_preserves_legacy_rows", rows(legacy) == before, rows(legacy))
        command.upgrade(config, "head")
        again = rows(legacy)
        check("reupgrade_preserves_legacy_rows", again == after, again)
        command.check(config)
        check("reupgraded_schema_matches", True)
        clean = Path(directory) / "clean.db"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{clean}"
        command.upgrade(config, "head")
        command.check(config)
        check("clean_install_schema_matches", True)
        with sqlite3.connect(clean) as connection:
            columns = {
                row[1]: row for row in connection.execute("PRAGMA table_info(teams)")
            }
        check("clean_install_field_exists", field in columns)
        check(
            "clean_install_field_not_null", field in columns and columns[field][3] == 1
        )
    return True


def main() -> None:
    """Emit a machine-readable report and exit one on any failure or exception."""
    parser = argparse.ArgumentParser()
    parser.add_argument("field", choices=["description", "tagline"])
    parser.add_argument("maximum", type=int)
    args = parser.parse_args()
    previous_url = os.environ.get("DATABASE_URL")
    try:
        if args.maximum != {"description": 2000, "tagline": 160}[args.field]:
            raise ValueError("Maximum does not match the frozen task contract")
        check("all_scenarios_completed", run(args.field) is True)
    except Exception as error:
        check(
            "probe_exception",
            False,
            {
                "type": type(error).__name__,
                "message": str(error),
                "traceback": traceback.format_exc(),
            },
        )
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
    passed = sum(item["passed"] for item in RESULTS)
    print(
        "PROBE_JSON="
        + json.dumps(
            {
                "checks": RESULTS,
                "passed": passed,
                "total": len(RESULTS),
                "human_time_saved": "not measured",
            },
            ensure_ascii=False,
        )
    )
    sys.exit(0 if RESULTS and passed == len(RESULTS) else 1)


if __name__ == "__main__":
    main()
