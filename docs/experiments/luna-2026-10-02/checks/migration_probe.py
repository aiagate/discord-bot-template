"""Independent legacy-row migration probe; run inside a trial checkout."""
import json
import os
import sqlite3
from pathlib import Path
from tempfile import TemporaryDirectory
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BASELINE_HEAD = "7d5f0d6a2b31"
checks = []
def check(name, passed, detail=None):
    checks.append({"check": name, "passed": bool(passed), "detail": detail})

def row(path):
    with sqlite3.connect(path) as connection:
        connection.row_factory = sqlite3.Row
        return dict(connection.execute("SELECT * FROM users").fetchone())

def main():
    config = Config("alembic.ini")
    heads = ScriptDirectory.from_config(config).get_heads()
    check("one_new_head", len(heads) == 1 and heads[0] != BASELINE_HEAD, heads)
    with TemporaryDirectory(prefix="luna-migration-probe-") as directory:
        legacy = Path(directory) / "legacy.db"
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{legacy}"
        command.upgrade(config, BASELINE_HEAD)
        with sqlite3.connect(legacy) as connection:
            connection.execute("INSERT INTO users(id, display_name, email, version, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)", ("01ARZ3NDEKTSV4RRFFQ69G5FAV", "Legacy", "legacy@example.test", 7, "2026-01-01 00:00:00", "2026-02-01 00:00:00"))
        before = row(legacy)
        command.upgrade(config, "head")
        after = row(legacy)
        check("legacy_bio_empty", after.get("bio") == "", after)
        check("legacy_other_values_preserved", all(after.get(k) == v for k, v in before.items()), after)
        command.check(config)
        check("upgraded_schema_matches", True)
        command.downgrade(config, BASELINE_HEAD)
        check("downgrade_legacy_preserved", row(legacy) == before, row(legacy))
        command.upgrade(config, "head")
        again = row(legacy)
        check("reupgrade_legacy_preserved", again.get("bio") == "" and all(again.get(k) == v for k, v in before.items()), again)
        command.check(config)
        check("reupgraded_schema_matches", True)
        os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{Path(directory) / 'clean.db'}"
        command.upgrade(config, "head")
        command.check(config)
        check("clean_install_schema_matches", True)

if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        check("probe_exception", False, {"exception": type(error).__name__, "message": str(error)})
    print("PROBE_JSON=" + json.dumps({"checks": checks, "passed": sum(c["passed"] for c in checks), "total": len(checks)}, ensure_ascii=False))
