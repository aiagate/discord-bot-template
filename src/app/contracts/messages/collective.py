"""Portable inputs and durable records for the maid collective."""

from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Text = Annotated[str, Field(min_length=1)]
Identifier = Annotated[str, Field(pattern=r"^[a-zA-Z0-9_-]+$")]
Scope = Literal["master", "times"]
Purpose = Literal["conversation", "reflection", "work", "memory", "render"]
Lane = Literal["conversation", "work"]
ActivityStatus = Literal[
    "ready", "running", "sleeping", "waiting", "blocked", "done", "stopped"
]


class Record(BaseModel):
    """Reject unknown fields at model and persistence boundaries."""

    model_config = ConfigDict(
        extra="forbid", validate_assignment=True, allow_inf_nan=False
    )


class Character(Record):
    """One configured identity; peers receive only its public profile."""

    id: Identifier
    name: Text
    persona: Text
    public_profile: Text
    avatar_url: str | None = None
    work_guidance: str = ""


class Event(Record):
    """An immutable source attributed to the actual speaker or executor."""

    id: str
    sequence: int
    kind: str
    actor: str
    scope: Scope
    origin: str
    content: str
    occurred_at: float
    source: str = ""
    activity_id: str | None = None


class Activity(Record):
    """A support objective survives individual model runs."""

    id: str
    owner: Identifier
    objective: Text
    value: Text
    target: Text
    criteria: list[Text] = Field(min_length=1)
    next_step: str
    source: str
    instruction_source: str = ""
    status: ActivityStatus = "ready"
    version: int = 1
    reason: str = ""
    question: str = ""
    wake_at: float | None = None
    evidence: dict[str, str] = Field(default_factory=dict)
    remaining: list[str] = Field(default_factory=list)
    artifacts: list[str] = Field(default_factory=list)
    last_result: str = ""
    runs: int = 0


class ActivityChange(Record):
    """A single proposed change, validated against the current activity."""

    action: Literal["start", "update", "stop", "resume", "handoff"]
    activity_id: str | None = None
    expected_version: int | None = None
    objective: str = ""
    value: str = ""
    target: str = ""
    criteria: list[str] = Field(default_factory=list)
    next_step: str = ""
    reason: str = ""
    recipient: str | None = None


class Memory(Record):
    """An owned note record with Markdown content, provenance and version."""

    owner: str
    note_id: Identifier
    kind: Literal["fact", "interpretation", "unconfirmed"]
    section: Literal["profile", "timeline"]
    content: str
    sources: list[str]
    version: int = 1
    deleted: bool = False

    @property
    def key(self) -> str:
        """Return the owner-scoped note key."""
        return f"{self.owner}/{self.note_id}"


class MemoryCandidate(Memory):
    """An update must name the version it replaces (zero for creation)."""

    expected_version: int = 0


class Decision(Record):
    """The selected character's own words and intentions only."""

    speech: str | None = None
    change: ActivityChange | None = None
    memories: list[MemoryCandidate] = Field(default_factory=list)
    consult: str | None = None
    inspect: bool = False


class Report(Record):
    """Facts for a conversational report, never raw tool output."""

    achieved: list[str] = Field(default_factory=list)
    findings: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    uncertainty: list[str] = Field(default_factory=list)
    question: str = ""


class WorkResult(Record):
    """Observed results and a proposed continuation, not an implicit success."""

    summary: Text
    action: Literal["continue", "sleep", "ask", "done", "blocked", "handoff", "propose"]
    next_step: str = ""
    reason: str = ""
    wake_at: float | None = None
    recipient: str | None = None
    evidence: dict[str, Text] = Field(default_factory=dict)
    artifacts: list[str] = Field(default_factory=list)
    remaining: list[str] = Field(default_factory=list)
    memories: list[MemoryCandidate] = Field(default_factory=list)
    report: Report | None = None
    proposal: ActivityChange | None = None


class Speech(Record):
    """Durable facts and optional rendered words from the conversation model."""

    id: str
    character_id: str
    scope: Scope
    origin: str
    report: Report = Field(default_factory=Report)
    body: str | None = None
    activity_id: str | None = None
    activity_version: int | None = None
    status: Literal["unrendered", "ready", "sending", "sent", "unknown", "held"] = (
        "unrendered"
    )


class SpeechPart(Record):
    """A fixed payload; unknown sends require reconciliation before later parts."""

    id: str
    speech_id: str
    index: int
    destination: str
    body: Text
    status: Literal["ready", "sending", "sent", "unknown", "rejected", "held"] = "ready"
    attempted_at: float | None = None
    next_at: float = 0
    attempts: int = 0
    message_id: str | None = None
    error: str = ""


class CharacterState(Record):
    """Independent reflection schedule and projected memory versions."""

    id: str
    next_reflection: float = 0
    projection: dict[str, int] = Field(default_factory=dict)


class MemorySource(Record):
    """Track extraction separately for each memory owner and source."""

    owner: str
    event_id: str
    status: Literal["pending", "extracted"] = "pending"


class Omission(Record):
    """Explain exactly which sources were not sent to the model."""

    source_ids: list[str]
    reason: str


class ContextItem(Record):
    """Related records are removed together, preserving questions and corrections."""

    id: str
    priority: Literal["required", "high", "low"]
    sources: list[str]
    content: str


class CharacterContext(Record):
    """One input snapshot shared by conversation and work."""

    character: Character
    master: str
    peers: dict[str, str]
    scope: Scope
    purpose: Purpose
    trigger: Event
    now: float
    items: list[ContextItem]
    activity_versions: dict[str, int]
    memory_versions: dict[str, int]
    event_sequence: int
    times_speech_allowed: bool = True
    omissions: list[Omission] = Field(default_factory=list)


class WorkContext(Record):
    """A fresh Codex run uses a stable workspace and frozen input versions."""

    context: CharacterContext
    run_id: str
    workspace: Path
    references: dict[str, str]
    activity: Activity | None
    previous_results: list[str]
    recovery: bool = False
    attempt: int = 1


class ModelLimits(Record):
    """Provider-reported limits and the configured conservative input budget."""

    model: str
    input_tokens: int = Field(gt=0)
    output_tokens: int = Field(gt=0)
    output_reserve: int = Field(gt=0)
    margin: int = Field(ge=0)

    @property
    def budget(self) -> int:
        """Reserve output and counting margin before admitting input."""
        return self.input_tokens - self.output_reserve - self.margin


class InputAttempt(Record):
    """Count the complete request and keep the admitted sources auditable."""

    model: str
    budget: int
    tokens: int
    remaining: int
    sections: dict[str, int]
    included: list[str]
    omissions: list[Omission]
    limits: ModelLimits | None = None


class Turn(Record):
    """An idempotent trigger and its durable execution checkpoint."""

    id: str
    character_id: str
    trigger_id: str
    origin: str
    purpose: Purpose
    lane: Lane
    activity_id: str | None = None
    speech_id: str | None = None
    status: Literal["pending", "running", "applied", "retry", "held"] = "pending"
    next_at: float = 0
    attempts: int = 0
    error: str = ""
    context: CharacterContext | None = None
    output: str | None = None
    input_attempts: list[InputAttempt] = Field(default_factory=list)
    execution: dict[str, str] = Field(default_factory=dict)
    recovery: bool = False


class CollectiveState(Record):
    """Typed transaction snapshot; adapters persist only changed records."""

    characters: dict[str, CharacterState] = Field(default_factory=dict)
    events: dict[str, Event] = Field(default_factory=dict)
    turns: dict[str, Turn] = Field(default_factory=dict)
    activities: dict[str, Activity] = Field(default_factory=dict)
    memories: dict[str, Memory] = Field(default_factory=dict)
    memory_sources: dict[str, MemorySource] = Field(default_factory=dict)
    speeches: dict[str, Speech] = Field(default_factory=dict)
    parts: dict[str, SpeechPart] = Field(default_factory=dict)


class CollectiveSettings(Record):
    """Explicit positive operating bounds for a single-process collective."""

    reflection_seconds: float = Field(default=3600, gt=0)
    times_interval_seconds: float = Field(default=3600, gt=0)
    reflection_lane: Lane = "conversation"
    turn_timeout: float = Field(default=900, gt=0)
    retry_seconds: float = Field(default=30, gt=0)
    max_attempts: int = Field(default=3, gt=0)
    max_round: int = Field(default=3, gt=0)
    max_activity_runs: int = Field(default=24, gt=0)
    poll_seconds: float = Field(default=1, gt=0)
    guide_bytes: int = Field(default=32768, gt=0)
