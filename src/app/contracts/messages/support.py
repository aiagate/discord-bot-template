"""Support activities and the decisions that advance them."""

from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

Text = Annotated[str, Field(min_length=1, max_length=12000)]
Slug = Annotated[str, Field(pattern=r"^[a-z][a-z0-9_-]{0,63}$")]
Status = Literal[
    "ready", "running", "sleeping", "waiting", "done", "stopped", "exhausted"
]


class Record(BaseModel):
    """Reject malformed model output and preserve immutable snapshots."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class Character(Record):
    """A portable identity used for both decisions and expression."""

    id: Slug
    name: Annotated[str, Field(min_length=1, max_length=80)]
    perspective: Text
    voice: Text
    avatar_url: Annotated[str, Field(pattern=r"^https?://", max_length=2048)] | None = (
        None
    )


class Activity(Record):
    """An ongoing purpose, independent of any conversation or model turn."""

    id: str
    objective: Text
    criteria: Annotated[tuple[Text, ...], Field(min_length=1, max_length=12)]
    scope: Text
    character_id: Slug
    repositories: tuple[Text, ...] = ()
    status: Status = "ready"
    wake_at: float = Field(ge=0, allow_inf_nan=False)
    next_step: str = "支援対象の現状を確認し、目的に役立つ次の一手を選ぶ。"
    revision: int = 0
    runs: int = 0
    max_runs: int = Field(default=24, ge=1, le=1000)


class Memory(Record):
    """An interpretation linked to evidence from an actual run."""

    key: Slug
    content: Text


class Communication(Record):
    """Content deliberately selected for communication, independent of work logs."""

    content: Text
    reason: str = Field(default="", max_length=12000)
    evidence: tuple[Text, ...] = Field(default=(), max_length=20)
    uncertainty: str = Field(default="", max_length=12000)
    question: str = Field(default="", max_length=12000)

    def as_text(self) -> str:
        """Preserve every communication field when expression is unavailable."""
        parts = [self.content]
        for label, value in (
            ("理由", self.reason),
            ("根拠", "\n".join(self.evidence)),
            ("未確認事項", self.uncertainty),
            ("確認したいこと", self.question),
        ):
            if value:
                parts.append(f"{label}: {value}")
        return "\n\n".join(parts)


class Outcome(Record):
    """An agent's explicit decision, distinct from ending its model turn."""

    action: Literal["continue", "sleep", "ask", "complete", "handoff"]
    summary: Text
    rationale: Text
    next_step: str = Field(
        max_length=12000,
        description="completeの場合は必ず空文字。他は具体的な次の一手・再確認条件・質問。",
    )
    delay_seconds: int | None = Field(
        default=None,
        ge=60,
        le=2592000,
        description="sleepの場合だけ再確認までの秒数。他はnull。",
    )
    recipient: Slug | None = Field(
        default=None, description="handoffの場合だけ別の仲間のID。他はnull。"
    )
    evidence: tuple[Text, ...] = Field(default=(), max_length=20)
    achieved: tuple[int, ...] = Field(
        default=(),
        max_length=12,
        description="completeの場合は確認したcriteriaの0始まりの全番号。他は空配列。",
    )
    memories: tuple[Memory, ...] = Field(default=(), max_length=8)
    communication: Communication | None = None

    @model_validator(mode="after")
    def validate_decision(self) -> Self:
        """Require the information needed to carry out each decision."""
        if self.action == "complete":
            if not self.evidence or not self.achieved or self.next_step:
                raise ValueError(
                    "Completion needs evidence, criteria, and no remaining work"
                )
        elif not self.next_step.strip():
            raise ValueError("Unfinished support needs a next step or question")
        if (self.action == "sleep") != (self.delay_seconds is not None):
            raise ValueError("Only timed waiting has a required delay")
        if (self.action == "handoff") != (self.recipient is not None):
            raise ValueError("Only a handoff has a required recipient")
        if self.action in {"ask", "complete"} and self.communication is None:
            raise ValueError("Questions and completion must be reported")
        if self.action == "ask" and (
            self.communication is None or self.communication.question != self.next_step
        ):
            raise ValueError(
                "The communicated question must match the pending question"
            )
        if self.action != "complete" and self.achieved:
            raise ValueError("Only completion declares achieved criteria")
        if len({note.key for note in self.memories}) != len(self.memories):
            raise ValueError("Memory keys must be unique within a decision")
        return self


class DeliveryReceipt(Record):
    """Observed message identity and content returned by the delivery service."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    message_id: Text
    channel_id: Text
    sender_id: Text
    username: Text
    content: str
    created_at: float = Field(ge=0, allow_inf_nan=False)


class DiscordDestination(Record):
    """One bound Discord window, containing identifiers but no webhook token."""

    guild_id: int = Field(gt=0)
    channel_id: int = Field(gt=0)
    webhook_id: int = Field(gt=0)


class DeliveryAttempt(Record):
    """Persist an attempt before sending and its receipt before marking delivery."""

    started_at: float = Field(ge=0, allow_inf_nan=False)
    receipt: DeliveryReceipt | None = None


class Event(Record):
    """An immutable observation, original message, or execution record."""

    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=False)

    id: str
    activity_id: str
    kind: str
    actor: str
    content: str
    created_at: float
    delivery: DeliveryReceipt | None = None


class Continuity(Record):
    """Durable decision and delivery facts, independent of the tool-log window."""

    last_decision: Event | None = None
    last_delivery: Event | None = None
    pending_question: str | None = None


class RuntimeObservation(Record):
    """Timestamped runtime facts, with boolean configuration and no credentials."""

    component: Literal[
        "configuration", "discord", "webhook", "expression", "delivery", "conversation"
    ]
    status: Literal["configured", "success", "failure", "disconnected", "unknown"]
    observed_at: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    source: Text
    settings: dict[str, bool] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_observation(self) -> Self:
        """Distinguish an observation from the absence of one."""
        if (self.status == "unknown") != (self.observed_at is None):
            raise ValueError("Observed facts need a time; unknown facts have no time")
        return self


class Context(Record):
    """The same context boundary serves human-triggered and autonomous work."""

    activity: Activity
    character: Character
    colleagues: tuple[Character, ...]
    master: str
    events: tuple[Event, ...]
    workspace: Path
    task_root: Path
    repositories: tuple[Path, ...] = ()
    memory_root: Path
    evidence_root: Path
    continuity: Continuity = Field(default_factory=Continuity)
    runtime: tuple[RuntimeObservation, ...] = ()
    now: float


class Notice(Record):
    """Durable content that can be expressed and delivered independently."""

    id: str
    activity_id: str
    character_id: str
    message: Communication
    rendered: str | None = None

    @property
    def content(self) -> str:
        """Return complete fallback content without losing structured fields."""
        return self.message.as_text()
