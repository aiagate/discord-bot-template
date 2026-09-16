"""Single-process SQLite transactions and an OS-held runner lock."""

import fcntl
import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from typing import Any

from app.contracts.messages.collective import CollectiveState


class SQLiteCollectiveStore:
    """Keep typed JSON records atomic, with database-enforced record identity."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.path = self.root / "collective.sqlite"
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA user_version=1")
            db.execute(
                "CREATE TABLE IF NOT EXISTS records ("
                "kind TEXT NOT NULL, id TEXT NOT NULL, body TEXT NOT NULL, "
                "PRIMARY KEY(kind, id))"
            )

    @contextmanager
    def lock(self) -> Iterator[None]:
        """Reject a second runner until this process closes its file descriptor."""
        with (self.root / "runner.lock").open("a") as handle:
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error:
                raise RuntimeError(
                    "This data directory already has a runner"
                ) from error
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

    @staticmethod
    def _load(db: sqlite3.Connection) -> CollectiveState:
        # ponytail: full snapshots suit one master; query per lane if volume grows.
        values: dict[str, dict[str, Any]] = {}
        for kind, key, body in db.execute(
            "SELECT kind, id, body FROM records ORDER BY rowid"
        ):
            values.setdefault(kind, {})[key] = json.loads(body)
        return CollectiveState.model_validate(values)

    @contextmanager
    def transaction(self) -> Iterator[CollectiveState]:
        """Rollback failed changes; update only changed rows on success."""
        with closing(sqlite3.connect(self.path)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            state = self._load(db)
            before = state.model_dump(mode="json")
            yield state
            after = state.model_dump(mode="json")
            for kind, records in after.items():
                for key, body in records.items():
                    if before[kind].get(key) != body:
                        db.execute(
                            "INSERT INTO records VALUES (?, ?, ?) "
                            "ON CONFLICT(kind, id) DO UPDATE SET body=excluded.body",
                            (kind, key, json.dumps(body, ensure_ascii=False)),
                        )
                for key in before[kind].keys() - records.keys():
                    db.execute("DELETE FROM records WHERE kind=? AND id=?", (kind, key))

    def read(self) -> CollectiveState:
        """Return a validated consistent snapshot."""
        with closing(sqlite3.connect(self.path)) as db:
            return self._load(db)
