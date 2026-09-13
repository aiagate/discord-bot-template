"""SQLite lifecycle and a browsable Markdown projection of original evidence."""

import fcntl
import os
import sqlite3
import tempfile
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from typing import Any

from app.contracts.messages.conversation import (
    ConversationContext,
    ConversationDecision,
)
from app.contracts.messages.support import (
    Activity,
    Character,
    Communication,
    Context,
    Continuity,
    DeliveryAttempt,
    DeliveryReceipt,
    DiscordDestination,
    Event,
    Notice,
    Outcome,
    RuntimeObservation,
)
from app.infrastructure.workspace import guidance


def atomic_write(path: Path, content: str) -> None:
    """Replace one UTF-8 file without exposing a partial document."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, delete=False
    ) as file:
        temporary = Path(file.name)
        try:
            file.write(content)
            file.flush()
            os.fsync(file.fileno())
        except BaseException:
            temporary.unlink(missing_ok=True)
            raise
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def runner_lock(root: Path) -> Iterator[None]:
    """Allow one executor per data directory while keeping controls available."""
    root.mkdir(parents=True, exist_ok=True)
    with (root / "runner.lock").open("a") as file:
        try:
            fcntl.flock(file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError("このデータディレクトリでは既に実行中です。") from error
        try:
            yield
        finally:
            fcntl.flock(file, fcntl.LOCK_UN)


class LocalStore:
    """Commit work, evidence, memory updates, and notices in one transaction."""

    def __init__(self, root: Path) -> None:
        self.root = root.resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        with self._connection() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS activities (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, activity_id TEXT NOT NULL, data TEXT NOT NULL,
                    external_key TEXT UNIQUE, projected INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS notices (
                    id TEXT PRIMARY KEY, data TEXT NOT NULL,
                    delivered INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS memory_updates (
                    id INTEGER PRIMARY KEY, source_id TEXT NOT NULL, key TEXT NOT NULL,
                    content TEXT NOT NULL, projected INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS conversation_inputs (
                    event_id TEXT PRIMARY KEY, completed INTEGER NOT NULL DEFAULT 0
                );
                CREATE TABLE IF NOT EXISTS runtime_observations (
                    component TEXT PRIMARY KEY, data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discord_destination (
                    slot INTEGER PRIMARY KEY CHECK (slot = 1), data TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS discord_attempts (
                    notice_id TEXT PRIMARY KEY, data TEXT NOT NULL
                );
            """)

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        db = sqlite3.connect(self.root / "state.sqlite3", timeout=10)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def initialize(self) -> None:
        """Install editable identities and master context without overwriting them."""
        for resource in files("app.profiles").iterdir():
            if resource.name.endswith(".json"):
                path = self.root / "characters" / resource.name
                if not path.exists():
                    atomic_write(path, resource.read_text(encoding="utf-8"))
        master = self.root / "master.md"
        if not master.exists():
            atomic_write(
                master,
                "# マスター\n\n呼び方: マスター\n\nここに判断の参考となる思想や希望を記入する。\n",
            )
        for directory in ("evidence", "work", "messages"):
            (self.root / directory).mkdir(exist_ok=True)
        for character in self.characters():
            self.workspace(character.id)

    def workspace(self, character_id: str) -> Path:
        """Initialize one character's persistent workspace, preserving edits."""
        character = self.character(character_id)
        workspace = self.root / "work" / character.id
        for path in (
            workspace,
            workspace / "memory",
            workspace / "repos",
            workspace / ".tmp",
        ):
            if path.resolve() != path:
                raise ValueError("個人の作業領域を別の場所へリンクできません。")
            path.mkdir(parents=True, exist_ok=True)
        agents = workspace / "AGENTS.md"
        if not agents.exists():
            atomic_write(agents, guidance(self.root, character))
        return workspace

    def character(self, character_id: str) -> Character:
        """Read the identity shared by reasoning and expression."""
        for character in self.characters():
            if character.id == character_id:
                return character
        raise ValueError("キャラクターが見つかりません。")

    def characters(self) -> tuple[Character, ...]:
        """Load each portable character definition once per request."""
        return tuple(
            Character.model_validate_json(path.read_text())
            for path in sorted((self.root / "characters").glob("*.json"))
        )

    @staticmethod
    def _get(db: sqlite3.Connection, activity_id: str) -> Activity:
        row = db.execute(
            "SELECT data FROM activities WHERE id = ?", (activity_id,)
        ).fetchone()
        if row is None:
            raise ValueError("支援活動が見つかりません。")
        return Activity.model_validate_json(row["data"])

    @staticmethod
    def _put(db: sqlite3.Connection, activity: Activity, **updates: Any) -> Activity:
        updated = Activity.model_validate({**activity.model_dump(), **updates})
        db.execute(
            "UPDATE activities SET data = ? WHERE id = ?",
            (updated.model_dump_json(), updated.id),
        )
        return updated

    @staticmethod
    def _event(
        db: sqlite3.Connection,
        activity: Activity,
        kind: str,
        content: str,
        now: float,
        *,
        actor: str | None = None,
        external_key: str | None = None,
        delivery: DeliveryReceipt | None = None,
    ) -> Event:
        event = Event(
            id=uuid.uuid4().hex,
            activity_id=activity.id,
            kind=kind,
            actor=actor or activity.character_id,
            content=content,
            created_at=now,
            delivery=delivery,
        )
        db.execute(
            "INSERT INTO events (id, activity_id, data, external_key) "
            "VALUES (?, ?, ?, ?)",
            (event.id, activity.id, event.model_dump_json(), external_key),
        )
        return event

    @staticmethod
    def _notice(
        db: sqlite3.Connection,
        activity: Activity,
        content: str | Communication,
        *,
        rendered: str | None = None,
    ) -> None:
        notice = Notice(
            id=uuid.uuid4().hex,
            activity_id=activity.id,
            character_id=activity.character_id,
            message=Communication(content=content)
            if isinstance(content, str)
            else content,
            rendered=rendered,
        )
        db.execute(
            "INSERT INTO notices (id, data) VALUES (?, ?)",
            (notice.id, notice.model_dump_json()),
        )

    def create(
        self,
        objective: str,
        criteria: tuple[str, ...],
        scope: str,
        character_id: str,
        *,
        max_runs: int = 24,
        repositories: tuple[str, ...] = (),
        now: float | None = None,
    ) -> Activity:
        """Register a continuing purpose that is immediately eligible to run (U1)."""
        self.character(character_id)
        at = time.time() if now is None else now
        activity = Activity(
            id=uuid.uuid4().hex[:12],
            objective=objective,
            criteria=criteria,
            scope=scope,
            character_id=character_id,
            repositories=repositories,
            wake_at=at,
            max_runs=max_runs,
        )
        with self._connection() as db:
            db.execute(
                "INSERT INTO activities VALUES (?, ?)",
                (activity.id, activity.model_dump_json()),
            )
            self._event(
                db,
                activity,
                "mandate",
                activity.model_dump_json(indent=2),
                at,
                actor="master",
            )
        return activity

    def current(self, activity_id: str) -> Activity:
        """Read state independently of any running agent snapshot."""
        with self._connection() as db:
            return self._get(db, activity_id)

    def activities(self) -> tuple[Activity, ...]:
        """Return all retained support activities."""
        with self._connection() as db:
            return tuple(
                Activity.model_validate_json(row[0])
                for row in db.execute("SELECT data FROM activities ORDER BY rowid")
            )

    def inform(
        self,
        activity_id: str,
        content: str,
        *,
        observation: bool = False,
        external_key: str | None = None,
        now: float | None = None,
    ) -> Activity:
        """Preserve original input and wake only eligible support."""
        if not content.strip() or len(content) > 24000:
            raise ValueError("入力は1〜24000文字で指定してください。")
        at = time.time() if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            activity = self._get(db, activity_id)
            if (
                external_key
                and db.execute(
                    "SELECT 1 FROM events WHERE external_key = ?", (external_key,)
                ).fetchone()
            ):
                return activity
            self._event(
                db,
                activity,
                "observation" if observation else "input",
                content,
                at,
                actor="observation" if observation else "master",
                external_key=external_key,
            )
            blocked = activity.status in {"done", "stopped", "exhausted"} or (
                observation and activity.status == "waiting"
            )
            return self._put(
                db,
                activity,
                revision=activity.revision + 1,
                status=activity.status if blocked else "ready",
                wake_at=at,
            )

    def receive(
        self, activity_id: str, content: str, *, external_key: str | None = None
    ) -> None:
        """Save original conversation without changing work state or its revision."""
        if not content.strip() or len(content) > 24000:
            raise ValueError("入力は1〜24000文字で指定してください。")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            activity = self._get(db, activity_id)
            if (
                external_key
                and db.execute(
                    "SELECT 1 FROM events WHERE external_key = ?", (external_key,)
                ).fetchone()
            ):
                return
            event = self._event(
                db,
                activity,
                "conversation_input",
                content,
                time.time(),
                actor="master",
                external_key=external_key,
            )
            db.execute(
                "INSERT INTO conversation_inputs (event_id) VALUES (?)", (event.id,)
            )

    def pending_conversation(self) -> Event | None:
        """Read the earliest unanswered input, including after a process restart."""
        with self._connection() as db:
            row = db.execute(
                "SELECT e.data FROM events e JOIN conversation_inputs c "
                "ON c.event_id = e.id WHERE c.completed = 0 "
                "ORDER BY e.rowid LIMIT 1"
            ).fetchone()
            return None if row is None else Event.model_validate_json(row[0])

    def conversation_context(self, message: Event) -> ConversationContext:
        """Share identity and memory while keeping execution logs out of dialogue."""
        self.project()
        activity = self.current(message.activity_id)
        with self._connection() as db:
            rows = db.execute(
                "SELECT data FROM events WHERE activity_id = ? AND id != ? "
                "AND json_extract(data, '$.kind') IN "
                "('conversation_input', 'input', 'delivered', 'control', 'decision') "
                "AND (rowid < (SELECT rowid FROM events WHERE id = ?) "
                "OR json_extract(data, '$.kind') IN ('control', 'decision')) "
                "ORDER BY rowid DESC LIMIT 30",
                (activity.id, message.id, message.id),
            ).fetchall()
        return ConversationContext(
            message=message,
            character=self.character(activity.character_id),
            master=(self.root / "master.md").read_text(),
            history=tuple(Event.model_validate_json(row[0]) for row in reversed(rows)),
            memories={
                path.stem: path.read_text()
                for path in sorted(
                    (self.workspace(activity.character_id) / "memory").glob("*.md")
                )
            },
            activity=activity,
            continuity=self.continuity(activity.id),
            runtime=self.runtime(),
        )

    def finish_conversation(
        self, context: ConversationContext, decision: ConversationDecision
    ) -> bool:
        """Commit a reply and explicit work effects together, once per input."""
        message = context.message
        at = time.time()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            pending = db.execute(
                "SELECT 1 FROM conversation_inputs "
                "WHERE event_id = ? AND completed = 0",
                (message.id,),
            ).fetchone()
            if pending is None:
                return False
            activity = self._get(db, message.activity_id)
            newer_control = db.execute(
                "SELECT 1 FROM events WHERE activity_id = ? "
                "AND rowid > (SELECT rowid FROM events WHERE id = ?) "
                "AND json_extract(data, '$.kind') IN ('control', 'input') LIMIT 1",
                (activity.id, message.id),
            ).fetchone()
            superseded = decision.action != "reply" and newer_control is not None
            if not superseded and activity.revision != context.activity.revision:
                return False
            content = decision.content
            if superseded:
                content = (
                    "その後に届いた指示を優先し、以前の作業指示は適用しませんでした。"
                )
            elif decision.action == "work":
                self._event(db, activity, "input", message.content, at, actor="master")
                active = activity.status not in {"stopped", "done", "exhausted"}
                activity = self._put(
                    db,
                    activity,
                    status="ready" if active else activity.status,
                    wake_at=at,
                    revision=activity.revision + 1,
                )
                content += (
                    "\n\n依頼を保存し、担当者の次の判断へ届けました。"
                    if active
                    else "\n\n情報を保存しました。活動は終了または停止中のため、再開の指示が必要です。"
                )
            elif decision.action in {"stop", "resume"}:
                status = (
                    "stopped"
                    if decision.action == "stop"
                    else "ready"
                    if activity.runs < activity.max_runs
                    else "exhausted"
                )
                activity = self._put(
                    db,
                    activity,
                    status=status,
                    wake_at=at,
                    revision=activity.revision + 1,
                )
                self._event(db, activity, "control", status, at, actor="master")
                content += (
                    "\n\n"
                    + {
                        "stopped": "活動を停止し、実行中の処理にも中断を要求しました。",
                        "ready": "活動を再開できる状態にしました。",
                        "exhausted": "実行予算の追加が必要なため、再開していません。",
                    }[status]
                )
            self._event(
                db,
                activity,
                "superseded_conversation" if superseded else "conversation_decision",
                f"原文: {message.id}\n{decision.model_dump_json()}",
                at,
                actor=context.character.id,
            )
            self._notice(
                db,
                activity.model_copy(update={"character_id": context.character.id}),
                content,
            )
            db.execute(
                "UPDATE conversation_inputs SET completed = 1 WHERE event_id = ?",
                (message.id,),
            )
        return True

    def control(
        self,
        activity_id: str,
        *,
        resume: bool = False,
        budget: int | None = None,
        now: float | None = None,
    ) -> Activity:
        """Stop or explicitly resume with an optional execution budget."""
        at = time.time() if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            activity = self._get(db, activity_id)
            return self._control(db, activity, resume, budget, at)

    def _control(
        self,
        db: sqlite3.Connection,
        activity: Activity,
        resume: bool,
        budget: int | None,
        at: float,
    ) -> Activity:
        if budget is not None and not resume:
            raise ValueError("予算の変更には再開を指定してください。")
        maximum = activity.max_runs if budget is None else activity.runs + budget
        if budget is not None and (budget < 1 or maximum > 1000):
            raise ValueError("追加予算は1以上、累計1000以下で指定してください。")
        status = (
            "ready"
            if resume and activity.runs < maximum
            else "exhausted"
            if resume
            else "stopped"
        )
        updated = self._put(
            db,
            activity,
            status=status,
            max_runs=maximum,
            wake_at=at,
            revision=activity.revision + 1,
        )
        self._event(db, updated, "control", status, at, actor="master")
        return updated

    def command(self, activity_id: str, content: str, external_key: str) -> None:
        """Commit a control input and its fixed reply together, once per message."""
        if content not in {"!stop", "!resume", "!status"}:
            raise ValueError("未対応の操作です。")
        at = time.time()
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM events WHERE external_key = ?", (external_key,)
            ).fetchone():
                return
            activity = self._get(db, activity_id)
            self._event(
                db,
                activity,
                "command",
                content,
                at,
                actor="master",
                external_key=external_key,
            )
            if content == "!status":
                states = {
                    "ready": "次の実行を待っています",
                    "running": "取り組んでいます",
                    "sleeping": "再確認の時刻を待っています",
                    "waiting": "返答を待っています",
                    "done": "達成しました",
                    "stopped": "停止しています",
                    "exhausted": "実行予算に達しています",
                }
                text = f"{states[activity.status]}。\n{activity.next_step}"
                reply = Communication(content=f"{states[activity.status]}。")
            else:
                activity = self._control(db, activity, content == "!resume", None, at)
                text = {
                    "stopped": "支援を停止しました。実行中の処理にも停止を伝えます。",
                    "ready": "支援を再開できる状態にしました。",
                    "exhausted": "実行予算の追加が必要です。",
                }[activity.status]
                reply = Communication(content=text)
            self._notice(db, activity, reply, rendered=text)

    def claim(self, now: float) -> Activity | None:
        """Atomically select due work; model calls never select their own budget."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute(
                """SELECT data FROM activities
                WHERE json_extract(data, '$.status') IN ('ready', 'sleeping')
                  AND json_extract(data, '$.wake_at') <= ?
                ORDER BY json_extract(data, '$.wake_at'), rowid""",
                (now,),
            ).fetchall()
            for row in rows:
                activity = Activity.model_validate_json(row[0])
                if activity.runs >= activity.max_runs:
                    self._put(
                        db, activity, status="exhausted", revision=activity.revision + 1
                    )
                    self._notice(
                        db,
                        activity,
                        "実行予算を使い切ったため、支援を一時停止しました。",
                    )
                    continue
                updated = self._put(
                    db,
                    activity,
                    status="running",
                    runs=activity.runs + 1,
                    revision=activity.revision + 1,
                )
                self._event(db, updated, "started", f"試行 {updated.runs}", now)
                return updated
        return None

    def recover(self, now: float | None = None) -> None:
        """Recover unknown attempts only after the caller acquires the runner lock."""
        at = time.time() if now is None else now
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT data FROM activities "
                "WHERE json_extract(data, '$.status') = 'running'"
            ).fetchall():
                activity = Activity.model_validate_json(row[0])
                self._put(
                    db,
                    activity,
                    status="ready",
                    wake_at=at,
                    next_step="中断した試行の外部操作と成果物の状態を確認してから続ける。\n"
                    + activity.next_step,
                    revision=activity.revision + 1,
                )
                self._event(
                    db,
                    activity,
                    "interrupted",
                    "前回の実行結果は不明。状態を確認する。",
                    at,
                )

    def record(self, activity: Activity, kind: str, content: str, now: float) -> None:
        """Append execution observations independently of final model claims."""
        with self._connection() as db:
            self._event(db, activity, kind, content, now)

    def finish(self, activity: Activity, outcome: Outcome, now: float) -> bool:
        """Commit a decision, memory updates, and its notice together (U3–U6)."""
        if outcome.action == "complete" and sorted(outcome.achieved) != list(
            range(len(activity.criteria))
        ):
            raise ValueError("達成条件すべての確認が必要です。")
        if outcome.recipient:
            self.character(outcome.recipient)
            if outcome.recipient == activity.character_id:
                raise ValueError("引継ぎ先は別の仲間を指定してください。")
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._get(db, activity.id)
            event = self._event(
                db,
                activity,
                "decision"
                if current.revision == activity.revision
                else "superseded_decision",
                outcome.model_dump_json(indent=2),
                now,
            )
            if current.revision != activity.revision:
                return False
            status = {"complete": "done", "ask": "waiting", "sleep": "sleeping"}.get(
                outcome.action, "ready"
            )
            self._put(
                db,
                activity,
                status=status,
                wake_at=now + (outcome.delay_seconds or 0),
                next_step=outcome.next_step,
                character_id=outcome.recipient or activity.character_id,
                revision=activity.revision + 1,
            )
            for note in outcome.memories:
                db.execute(
                    "INSERT INTO memory_updates (source_id, key, content) "
                    "VALUES (?, ?, ?)",
                    (event.id, note.key, note.content),
                )
            if outcome.communication is not None:
                self._notice(db, activity, outcome.communication)
        return True

    def fail(self, activity: Activity, reason: str, now: float) -> None:
        """Save uncertain results and retry with backoff within the activity budget."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            current = self._get(db, activity.id)
            self._event(db, activity, "failed", reason, now)
            if current.revision != activity.revision:
                return
            self._put(
                db,
                activity,
                status="sleeping",
                wake_at=now + min(3600, 60 * 2 ** min(activity.runs - 1, 6)),
                next_step=reason + "\n" + activity.next_step,
                revision=activity.revision + 1,
            )
            self._notice(db, activity, reason)

    def events(self, activity_id: str) -> tuple[Event, ...]:
        """Read original observations and decisions for one activity."""
        with self._connection() as db:
            return tuple(
                Event.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT data FROM events WHERE activity_id = ? ORDER BY rowid",
                    (activity_id,),
                )
            )

    def project(self) -> None:
        """Retry durable Markdown writes without re-executing model work."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in db.execute(
                "SELECT data FROM events WHERE projected = 0 ORDER BY rowid"
            ).fetchall():
                event = Event.model_validate_json(row[0])
                content = (
                    f"# {event.kind}\n\n活動: {event.activity_id}\n担当: {event.actor}\n"
                    f"時刻: {event.created_at}\n\n{event.content}\n"
                )
                atomic_write(self.root / "evidence" / f"{event.id}.md", content)
                db.execute("UPDATE events SET projected = 1 WHERE id = ?", (event.id,))
            for row in db.execute(
                "SELECT * FROM memory_updates WHERE projected = 0 ORDER BY id"
            ).fetchall():
                source = db.execute(
                    "SELECT data FROM events WHERE id = ?", (row["source_id"],)
                ).fetchone()
                event = Event.model_validate_json(source[0])
                directory = self.workspace(event.actor) / "memory"
                reference = os.path.relpath(
                    self.root / "evidence" / f"{event.id}.md", directory
                )
                content = (
                    f"# {row['key']}\n\n担当者が整理した理解・経験。\n"
                    f"出典: {reference}\n\n{row['content']}\n"
                )
                atomic_write(directory / f"{row['key']}.md", content)
                db.execute(
                    "UPDATE memory_updates SET projected = 1 WHERE id = ?", (row["id"],)
                )

    def context(self, activity: Activity, now: float) -> Context:
        """Expose policy and filesystem paths on every autonomous or direct attempt."""
        self.project()
        workspace = self.workspace(activity.character_id)
        task_root = workspace / "tasks" / activity.id
        if task_root.resolve() != task_root:
            raise ValueError("活動の作業場所を別の場所へリンクできません。")
        task_root.mkdir(parents=True, exist_ok=True)
        colleagues = self.characters()
        context = Context(
            activity=activity,
            character=self.character(activity.character_id),
            colleagues=colleagues,
            master=(self.root / "master.md").read_text(),
            events=self.events(activity.id)[-30:],
            workspace=workspace,
            task_root=task_root,
            memory_root=workspace / "memory",
            evidence_root=self.root / "evidence",
            continuity=self.continuity(activity.id),
            runtime=self.runtime(),
            now=now,
        )
        atomic_write(task_root / "context.json", context.model_dump_json(indent=2))
        return context

    def continuity(self, activity_id: str) -> Continuity:
        """Fetch accepted decisions and actual delivery outside the tool-log window."""
        with self._connection() as db:

            def latest(kind: str) -> Event | None:
                row = db.execute(
                    "SELECT data FROM events WHERE activity_id = ? "
                    "AND json_extract(data, '$.kind') = ? ORDER BY rowid DESC LIMIT 1",
                    (activity_id, kind),
                ).fetchone()
                return Event.model_validate_json(row[0]) if row else None

            decision = latest("decision")
            pending = None
            if decision is not None:
                outcome = Outcome.model_validate_json(decision.content)
                answered = db.execute(
                    "SELECT 1 FROM events WHERE activity_id = ? "
                    "AND rowid > (SELECT rowid FROM events WHERE id = ?) "
                    "AND json_extract(data, '$.kind') = 'input' LIMIT 1",
                    (activity_id, decision.id),
                ).fetchone()
                if outcome.action == "ask" and answered is None:
                    pending = outcome.next_step
            return Continuity(
                last_decision=decision,
                last_delivery=latest("delivered"),
                pending_question=pending,
            )

    def observe(self, observation: RuntimeObservation) -> None:
        """Save a runtime fact without changing work state or waking an activity."""
        with self._connection() as db:
            self._observe(db, observation)

    @staticmethod
    def _observe(db: sqlite3.Connection, observation: RuntimeObservation) -> None:
        db.execute(
            "INSERT OR REPLACE INTO runtime_observations VALUES (?, ?)",
            (observation.component, observation.model_dump_json()),
        )

    def runtime(self) -> tuple[RuntimeObservation, ...]:
        """Return last observations, explicitly identifying unobserved components."""
        with self._connection() as db:
            known = {
                item.component: item
                for row in db.execute("SELECT data FROM runtime_observations")
                for item in (RuntimeObservation.model_validate_json(row[0]),)
            }
        return tuple(
            known.get(component)
            or RuntimeObservation(
                component=component, status="unknown", source="基盤による観測記録なし"
            )
            for component in (
                "configuration",
                "discord",
                "webhook",
                "expression",
                "delivery",
                "conversation",
            )
        )

    def pending_notices(self) -> tuple[Notice, ...]:
        """Read saved, undelivered communication intents."""
        with self._connection() as db:
            return tuple(
                Notice.model_validate_json(row[0])
                for row in db.execute(
                    "SELECT data FROM notices WHERE delivered = 0 ORDER BY rowid"
                )
            )

    def discord_destination(self) -> DiscordDestination | None:
        """Read the bound window without exposing the webhook URL."""
        with self._connection() as db:
            row = db.execute(
                "SELECT data FROM discord_destination WHERE slot = 1"
            ).fetchone()
            return DiscordDestination.model_validate_json(row[0]) if row else None

    def bind_discord(self, destination: DiscordDestination) -> None:
        """Keep queued messages in the same window across process restarts."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM discord_destination WHERE slot = 1"
            ).fetchone()
            if row and DiscordDestination.model_validate_json(row[0]) != destination:
                raise ValueError("保存されたDiscordの送信先と一致しません。")
            db.execute(
                "INSERT OR IGNORE INTO discord_destination VALUES (1, ?)",
                (destination.model_dump_json(),),
            )

    def discord_attempt(self, notice_id: str) -> DeliveryAttempt | None:
        """Read a potentially unconfirmed send before another attempt."""
        with self._connection() as db:
            row = db.execute(
                "SELECT data FROM discord_attempts WHERE notice_id = ?", (notice_id,)
            ).fetchone()
            return DeliveryAttempt.model_validate_json(row[0]) if row else None

    def save_discord_attempt(self, notice_id: str, attempt: DeliveryAttempt) -> None:
        """Persist the send boundary and any observed receipt independently of work."""
        with self._connection() as db:
            db.execute(
                "INSERT OR REPLACE INTO discord_attempts VALUES (?, ?)",
                (notice_id, attempt.model_dump_json()),
            )

    def reset_discord_attempt(self, notice_id: str) -> None:
        """Allow another send only after a definite request rejection."""
        with self._connection() as db:
            db.execute("DELETE FROM discord_attempts WHERE notice_id = ?", (notice_id,))

    def save_rendered(self, notice_id: str, content: str) -> None:
        """Keep wording stable when delivery is retried."""
        with self._connection() as db:
            row = db.execute(
                "SELECT data FROM notices WHERE id = ?", (notice_id,)
            ).fetchone()
            if row is None:
                raise ValueError("報告が見つかりません。")
            notice = Notice.model_validate_json(row[0]).model_copy(
                update={"rendered": content}
            )
            db.execute(
                "UPDATE notices SET data = ? WHERE id = ?",
                (notice.model_dump_json(), notice_id),
            )

    def delivered(self, notice_id: str, receipt: DeliveryReceipt | None = None) -> None:
        """Record the delivered words as conversation, leaving work state intact."""
        with self._connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT data FROM notices WHERE id = ? AND delivered = 0", (notice_id,)
            ).fetchone()
            if row is None:
                return
            notice = Notice.model_validate_json(row[0])
            self._event(
                db,
                self._get(db, notice.activity_id),
                "delivered",
                notice.rendered or notice.content,
                time.time(),
                actor=notice.character_id,
                delivery=receipt,
            )
            db.execute("UPDATE notices SET delivered = 1 WHERE id = ?", (notice_id,))
            self._observe(
                db,
                RuntimeObservation(
                    component="delivery",
                    status="success",
                    observed_at=time.time(),
                    source=f"notice:{notice.id}",
                ),
            )
